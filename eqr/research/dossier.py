"""Claude dossier runner. Builds the pack, prompts Claude (CLI on the Mac, or the API),
validates the JSON against the schema + citation rule, stores JSON and Markdown.
A run that fails validation stores nothing."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import duckdb

from ..config import settings
from .pack import build_pack
from .schema import validate_dossier

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
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    r = subprocess.run([cli, "-p", "--model", model, "--output-format", "text", "--tools", ""],
                       input=prompt, capture_output=True, text=True, timeout=900, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {r.stderr[:500]}")
    return r.stdout


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


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
    text = response_text if response_text is not None else _call_claude(prompt, model)
    (path / "response.txt").write_text(text)
    try:
        obj = _extract_json(text)
    except ValueError as e:
        return {"status": "REJECTED", "errors": [str(e)]}
    allowed = {d["doc_id"] for d in pack["documents"]}
    errors = validate_dossier(obj, allowed)
    if errors:
        (path / "validation_errors.json").write_text(json.dumps(errors, indent=1))
        return {"status": "REJECTED", "errors": errors}
    md = render_markdown(obj)
    (path / "dossier.md").write_text(md)
    con.execute("INSERT OR REPLACE INTO dossiers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [symbol, obj["as_of"], model, obj["rating"], float(obj["confidence"]), json.dumps(obj), md, datetime.now()])
    return {"status": "STORED", "rating": obj["rating"], "confidence": obj["confidence"], "path": str(path / "dossier.md")}
