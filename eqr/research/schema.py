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


def validate_dossier(obj: dict, allowed_docs: set[str]) -> list[str]:
    errors = [f"{'/'.join(str(p) for p in e.path) or '$'}: {e.message}" for e in _validator.iter_errors(obj)]
    if errors:
        return errors
    cites: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "citations" and isinstance(v, list):
                    cites.update(str(c) for c in v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    bad = []
    for c in cites:
        if c in TABLE_CITATIONS:
            continue
        if DOC_RX.match(c) and c.split("#")[0][4:] in allowed_docs:
            continue
        bad.append(c)
    if bad:
        errors.append(f"unknown citations: {sorted(bad)[:10]}")
    return errors
