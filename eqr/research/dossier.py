"""Claude dossier runner. Builds the pack, prompts Claude (CLI on the Mac, or the API),
validates the JSON against the schema + citation rule, stores JSON and Markdown.
A run that fails validation stores nothing."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from ..config import settings
from ..store import upsert
from .pack import build_pack
from .schema import validate_dossier
from .verify import REJECT_STRUCK_SHARE, verify_web_claims
from .webresearch import run_webresearch

DOSSIER_SCHEMA_VERSION = 1

SYSTEM = """You are an equity research analyst writing an evidence-bound dossier on an Indian listed company.
Rules: use ONLY the pack provided. Every claim, assessment and catalyst must carry citations to doc:<doc_id>
(add #p<page> when you can) or table:<name>. If the pack lacks the evidence for a point, list it under data_gaps
instead of asserting it. Numbers are in INR crores unless stated. Be specific, sceptical and concise.
Your output must be exactly one JSON object matching the schema below (no prose before or after it)."""

SYSTEM_WEB = """The pack also carries a `web` array of recent web sources (id `web:<src_id>`). You MAY cite a web
source as web:<src_id> in bull_case, bear_case, red_flags or catalysts to add recency or external colour. When you
cite a web source, the item MUST also carry a `quote` field copied VERBATIM (a 15-400 char exact substring) from
that source's excerpt — a deterministic checker will strike any web claim whose quote is not found in its source.
Web sources add colour only: they never override the pack's numbers, ratings or gates. Assessments must cite the
pack's tables/documents, not the web."""


def _prompt(pack: dict, schema: dict, extra_system: str = "") -> str:
    slim = {k: v for k, v in pack.items() if not k.startswith("_")}
    system = SYSTEM + (("\n\n" + extra_system) if extra_system else "")
    return (f"{system}\n\nSCHEMA:\n{json.dumps(schema)}\n\nPACK:\n{json.dumps(slim, default=str)}\n\n"
            f"Write the dossier for {pack['symbol']} as of {pack['as_of']}. Output the JSON object only.")


def _call_claude(prompt: str, model: str) -> str:
    key = settings().anthropic_api_key
    if key:
        import urllib.request
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", method="POST",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            data=json.dumps({"model": model, "max_tokens": 6000,
                             "messages": [{"role": "user", "content": prompt}]}).encode())
        with urllib.request.urlopen(req, timeout=600) as r:
            body = json.loads(r.read())
        return "".join(b.get("text", "") for b in body.get("content", []))
    cli = shutil.which("claude")
    if not cli:
        raise RuntimeError("neither ANTHROPIC_API_KEY nor the `claude` CLI is available")
    # a clean environment: the desktop app's proxied auth and nested-session markers must not leak
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC"))}
    r = subprocess.run([cli, "-p", "--model", model, "--output-format", "text", "--bare", "--tools", ""],
                       input=prompt, capture_output=True, text=True, timeout=900, env=env)
    if r.returncode != 0:
        err = "\n".join(l for l in r.stderr.splitlines() if "Permission allow rule" not in l and "Use Edit(" not in l)
        raise RuntimeError(f"claude CLI failed (run `eqr dossier` from a terminal where `claude` is logged in, "
                           f"or set ANTHROPIC_API_KEY): {err[:400]}")
    return r.stdout


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


_PAGE_CITE = re.compile(r"^doc:([A-Za-z0-9_\-]+)#p(\d+)$")


def _all_citations(obj: dict) -> list[str]:
    out: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "citations" and isinstance(v, list):
                    out.extend(str(c) for c in v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return out


def _binding_errors(obj: dict, symbol: str, pack: dict) -> list[str]:
    """The response must be bound to the request: right symbol, right as_of, and no page
    citation beyond a cited document's length."""
    errors = []
    if obj.get("symbol") != symbol:
        errors.append(f"symbol mismatch: dossier {obj.get('symbol')!r} != request {symbol!r}")
    if str(obj.get("as_of")) != str(pack["as_of"]):
        errors.append(f"as_of mismatch: dossier {obj.get('as_of')!r} != pack {pack['as_of']!r}")
    pages_by_doc = {d["doc_id"]: int(d.get("pages") or 0) for d in pack["documents"]}
    for c in _all_citations(obj):
        m = _PAGE_CITE.match(c)
        if m and m.group(1) in pages_by_doc:
            limit = pages_by_doc[m.group(1)]
            if limit and int(m.group(2)) > limit:
                errors.append(f"citation {c} exceeds document pages ({limit})")
    return errors


def render_markdown(d: dict) -> str:
    def claims(items):
        return "\n".join(f"- {c['claim']} _{' '.join(c['citations'])}_" for c in items) or "- none"
    a = d["assessments"]
    md = [f"# {d['symbol']} — research dossier (as of {d['as_of']})", "",
          f"**Rating: {d['rating']}** · confidence {d['confidence']:.0%}" + (f" · horizon {d['horizon_months']}m" if d.get("horizon_months") else ""),
          "", "## Thesis", "", d["thesis"], "", "## Assessments", "", "| Area | Score | Summary |", "|---|---|---|"]
    md += [f"| {k.title()} | {a[k]['score']}/5 | {a[k]['summary']} _{' '.join(a[k]['citations'])}_ |" for k in ("quality", "valuation", "momentum", "governance")]
    md += ["", "## Bull case", "", claims(d["bull_case"]), "", "## Bear case", "", claims(d["bear_case"]),
           "", "## Red flags", "", claims(d["red_flags"]), "", "## Catalysts", ""]
    md += [f"- {c['event']} — {c['expected_by']} ({c['direction']}) _{' '.join(c['citations'])}_" for c in d["catalysts"]] or ["- none"]
    md += ["", "## What would change my mind", ""] + [f"- {x}" for x in d["what_would_change_my_mind"]]
    md += ["", "## Data gaps", ""] + ([f"- {x}" for x in d["data_gaps"]] or ["- none"])
    return "\n".join(md)


def run_dossier(con: duckdb.DuckDBPyConnection, symbol: str, as_of: Optional[date] = None,
                model: Optional[str] = None, dry_run: bool = False, response_text: Optional[str] = None,
                web: bool = True) -> dict:
    """Auto-web is ON by default: gather web evidence (fail-soft), build a web-enriched pack, prompt
    Claude, validate + bind, verify web quotes deterministically, and store the dossier plus its
    claim rows. Wave-1 doctrine: web evidence enriches TEXT only — it never touches numbers."""
    model = model or settings().claude_model
    wr_status = None
    if web:
        try:
            wr_status = (run_webresearch(con, symbol, as_of) or {}).get("status")
        except Exception as e:                            # never let web research sink the dossier
            wr_status = "FAILED"
            logging.getLogger("eqr.dossier").warning("webresearch failed for %s: %s", symbol, e)
    pack = build_pack(con, symbol, as_of, web=web)
    web_rows = pack.get("web") or []
    allowed_web = frozenset(w["src_id"] for w in web_rows)
    from .schema import SCHEMA
    prompt = _prompt(pack, SCHEMA, SYSTEM_WEB if web_rows else "")
    path = Path(pack["_path"])
    (path / "prompt.txt").write_text(prompt)
    if dry_run:
        return {"status": "DRY_RUN", "prompt_path": str(path / "prompt.txt"), "prompt_chars": len(prompt),
                "documents": len(pack["documents"]), "web_sources": len(web_rows), "webresearch": wr_status}
    run_id = f"dossier-{symbol}-{pack['as_of']}-{uuid.uuid4().hex[:8]}"

    def _reject(errors: list) -> dict:
        (path / "validation_errors.json").write_text(json.dumps(errors, indent=1))
        con.execute("INSERT INTO dossiers (run_id, symbol, as_of, model, status, errors_json, created_at) "
                    "VALUES (?, ?, ?, ?, 'REJECTED', ?, ?)",
                    [run_id, symbol, pack["as_of"], model, json.dumps(errors), datetime.now()])
        return {"status": "REJECTED", "run_id": run_id, "errors": errors}

    text = response_text if response_text is not None else _call_claude(prompt, model)
    (path / "response.txt").write_text(text)
    try:
        obj = _extract_json(text)
    except ValueError as e:
        return _reject([str(e)])
    allowed = {d["doc_id"] for d in pack["documents"]}
    errors = validate_dossier(obj, allowed, allowed_web)
    if errors:
        return _reject(errors)
    binding = _binding_errors(obj, symbol, pack)
    if binding:
        return _reject(binding)

    # deterministic web-quote verification (a no-op when web is off / there are no web citations)
    texts = {w["src_id"]: w["excerpt"] for w in web_rows}
    if web:
        pruned, claim_rows, n_web, n_struck = verify_web_claims(obj, texts)
        if n_web and (n_struck / n_web) > REJECT_STRUCK_SHARE:
            return _reject([f"{n_struck}/{n_web} web quotes unsupported (> {REJECT_STRUCK_SHARE:.0%})"])
        if pruned is not obj:
            rev = validate_dossier(pruned, allowed, allowed_web)
            if rev:
                return _reject(["after striking unsupported web claims: " + e for e in rev])
    else:
        pruned, claim_rows, n_web, n_struck = obj, [], 0, 0

    md = render_markdown(pruned)
    (path / "dossier.md").write_text(md)
    con.execute(
        "INSERT INTO dossiers (run_id, symbol, as_of, model, rating, confidence, json, markdown, status, schema_version, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'STORED', ?, ?)",
        [run_id, symbol, pruned["as_of"], model, pruned["rating"], float(pruned["confidence"]),
         json.dumps(pruned), md, DOSSIER_SCHEMA_VERSION, datetime.now()])
    if web:
        if claim_rows:
            upsert(con, "dossier_claims", pd.DataFrame(
                [dict(r, run_id=run_id, symbol=symbol, as_of=pack["as_of"]) for r in claim_rows]))
        upsert(con, "research_runs", pd.DataFrame([{
            "run_id": run_id, "symbol": symbol, "as_of": pack["as_of"], "mode": "dossier_web",
            "model": model, "status": "STORED", "cost_usd": 0.0,
            "passes_json": json.dumps({"web_claims": n_web, "struck": n_struck,
                                       "webresearch_status": wr_status}),
            "started_at": datetime.now(), "ended_at": datetime.now()}]))
    return {"status": "STORED", "run_id": run_id, "rating": pruned["rating"], "confidence": pruned["confidence"],
            "path": str(path / "dossier.md"), "web_claims": n_web, "struck": n_struck, "webresearch": wr_status}
