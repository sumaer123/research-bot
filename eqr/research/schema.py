"""Dossier JSON schema + the citation rule: every citation must name a doc_id or a
table that exists in the pack. Unsupported claims fail validation; nothing partial is stored."""
from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA = json.loads(Path(__file__).with_name("schema.json").read_text())
_validator = Draft202012Validator(SCHEMA)
TABLE_CITATIONS = {"table:prices", "table:features", "table:ranks", "table:statements", "table:shareholding",
                   "table:surveillance", "table:deals", "table:announcements", "table:peers", "table:regime",
                   "table:corporate_actions", "table:results_calendar"}
DOC_RX = re.compile(r"^doc:[A-Za-z0-9_\-]+(?:#p\d+)?$")
WEB_RX = re.compile(r"^web:[A-Za-z0-9_\-]+$")


def validate_dossier(obj: dict, allowed_docs: set[str], allowed_web: frozenset[str] = frozenset()) -> list[str]:
    """Citation rule: every citation names a known table, a pack document, or a web source in
    `allowed_web`. A web-cited claim/assessment/catalyst MUST carry a verbatim `quote` (Wave-1:
    web evidence is auditable text, never a bare assertion)."""
    errors = [f"{'/'.join(str(p) for p in e.path) or '$'}: {e.message}" for e in _validator.iter_errors(obj)]
    if errors:
        return errors
    bad: list[str] = []
    web_without_quote: list[str] = []

    def check(cites: list, quote) -> None:
        web_here = [str(c) for c in cites if WEB_RX.match(str(c))]
        for c in cites:
            c = str(c)
            if c in TABLE_CITATIONS:
                continue
            if DOC_RX.match(c) and c.split("#")[0][4:] in allowed_docs:
                continue
            if WEB_RX.match(c) and c[4:] in allowed_web:
                continue
            bad.append(c)
        if web_here and not (isinstance(quote, str) and quote.strip()):
            web_without_quote.append(web_here[0])

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("citations"), list):
                check(x["citations"], x.get("quote"))
            for k, v in x.items():
                if k != "citations":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    if bad:
        errors.append(f"unknown citations: {sorted(set(bad))[:10]}")
    if web_without_quote:
        errors.append(f"web citation without a verbatim quote: {sorted(set(web_without_quote))[:10]}")
    return errors
