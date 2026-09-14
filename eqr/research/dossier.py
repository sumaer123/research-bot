"""Claude dossier runner. Builds the pack, prompts Claude (CLI on the Mac, or the API),
validates the JSON against the schema + citation rule, stores JSON and Markdown.
A run that fails validation stores nothing."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import duckdb

from ..config import settings
from .pack import build_pack
from .schema import validate_dossier

DOSSIER_SCHEMA_VERSION = 1

SYSTEM = """You are an equity research analyst writing an evidence-bound dossier on an Indian listed company.
Rules: use ONLY the pack provided. Every claim, assessment and catalyst must carry citations to doc:<doc_id>
(add #p<page> when you can) or table:<name>. If the pack lacks the evidence for a point, list it under data_gaps
instead of asserting it. Numbers are in INR crores unless stated. Be specific, sceptical and concise.
Your output must be exactly one JSON object matching the schema below (no prose before or after it)."""


def _prompt(pack: dict, schema: dict) -> str:
    slim = {k: v for k, v in pack.items() if not k.startswith("_")}
    return (f"{SYSTEM}\n\nSCHEMA:\n{json.dumps(schema)}\n\nPACK:\n{json.dumps(slim, default=str)}\n\n"
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
                model: Optional[str] = None, dry_run: bool = False, response_text: Optional[str] = None) -> dict:
    model = model or settings().claude_model
    pack = build_pack(con, symbol, as_of)
    from .schema import SCHEMA
    prompt = _prompt(pack, SCHEMA)
    path = Path(pack["_path"])
    (path / "prompt.txt").write_text(prompt)
    if dry_run:
        return {"status": "DRY_RUN", "prompt_path": str(path / "prompt.txt"), "prompt_chars": len(prompt),
                "documents": len(pack["documents"])}
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
    errors = validate_dossier(obj, allowed)
    if errors:
        return _reject(errors)
    binding = _binding_errors(obj, symbol, pack)
    if binding:
        return _reject(binding)
    md = render_markdown(obj)
    (path / "dossier.md").write_text(md)
    con.execute(
        "INSERT INTO dossiers (run_id, symbol, as_of, model, rating, confidence, json, markdown, status, schema_version, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'STORED', ?, ?)",
        [run_id, symbol, obj["as_of"], model, obj["rating"], float(obj["confidence"]), json.dumps(obj), md,
         DOSSIER_SCHEMA_VERSION, datetime.now()])
    return {"status": "STORED", "run_id": run_id, "rating": obj["rating"], "confidence": obj["confidence"],
            "path": str(path / "dossier.md")}
