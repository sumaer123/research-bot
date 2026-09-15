"""Deterministic web-claim verifier. Pure code over (dossier obj, {src_id: text}); it never sees
the prompt, pack, or model (the graph-of-loops fresh-context checker). A claim that web-cites a
source must carry a verbatim `quote` that is an exact or >=0.90 fuzzy substring of that source's
stored text; unsupported claims are struck and their text is moved to data_gaps. Assessments are
recorded but never struck (they cite the pack's numbers, not the web)."""
from __future__ import annotations

import copy
import json
import re
from difflib import SequenceMatcher

from .schema import WEB_RX

REJECT_STRUCK_SHARE = 0.25
FUZZY_MIN = 0.90
_WS = re.compile(r"\s+")

# Sections whose items are list entries and may be pruned. Assessments are structural (schema
# requires all four) so they are recorded, not struck.
PRUNABLE = ("bull_case", "bear_case", "red_flags", "catalysts")
_TEXT_FIELD = {"bull_case": "claim", "bear_case": "claim", "red_flags": "claim", "catalysts": "event"}


def normalise(text: str) -> str:
    return _WS.sub(" ", (text or "").lower()).strip()


def quote_supported(quote: str, text: str, fuzzy_min: float = FUZZY_MIN) -> tuple[bool, float, str]:
    nq = normalise(quote)
    nt = normalise(text)
    if not nq:
        return False, 0.0, "empty"
    if nq in nt:
        return True, 1.0, "exact"
    if not nt:
        return False, 0.0, "none"
    L = len(nq)
    step = max(1, L // 4)
    best = 0.0
    for i in range(0, max(1, len(nt) - L + 1), step):
        r = SequenceMatcher(None, nq, nt[i:i + L]).ratio()
        if r > best:
            best = r
        if best >= 1.0:
            break
    ok = best >= fuzzy_min
    return ok, round(best, 3), ("fuzzy" if ok else "none")


def _web_ids(citations) -> list[str]:
    return [str(c)[4:] for c in (citations or []) if WEB_RX.match(str(c))]


def web_claim_rows(obj: dict) -> list[dict]:
    """Descriptors for every citation-bearing item (both web and non-web), for reuse / inspection."""
    rows: list[dict] = []
    for section in PRUNABLE:
        for i, item in enumerate(obj.get(section) or []):
            rows.append({"section": section, "index": i, "text": item.get(_TEXT_FIELD[section], ""),
                         "citations": item.get("citations", []), "quote": item.get("quote"),
                         "web_ids": _web_ids(item.get("citations"))})
    for name, a in (obj.get("assessments") or {}).items():
        rows.append({"section": f"assessment:{name}", "index": 0, "text": a.get("summary", ""),
                     "citations": a.get("citations", []), "quote": a.get("quote"),
                     "web_ids": _web_ids(a.get("citations"))})
    return rows


def _row(section, idx, text, cites, quote, verified, method, score, note) -> dict:
    return {"claim_id": f"{section}-{idx}", "section": section, "text": text,
            "citations_json": json.dumps(cites), "quote": quote, "table_ref_json": None,
            "verified": verified, "verify_method": method, "verify_score": score, "verifier_note": note}


def verify_web_claims(obj: dict, texts: dict[str, str],
                      fuzzy_min: float = FUZZY_MIN) -> tuple[dict, list[dict], int, int]:
    """Return (pruned_obj, claim_rows, n_web, n_struck). Struck items are removed from their list
    and summarised into data_gaps. Non-web items are rows with verify_method='unverified'."""
    pruned = copy.deepcopy(obj)
    rows: list[dict] = []
    n_web = 0
    struck_texts: list[str] = []

    for section in PRUNABLE:
        kept = []
        for i, item in enumerate(pruned.get(section) or []):
            text = item.get(_TEXT_FIELD[section], "")
            cites = item.get("citations", [])
            web_ids = _web_ids(cites)
            if web_ids:
                n_web += 1
                combined = "\n".join(texts.get(w, "") for w in web_ids)
                ok, score, method = quote_supported(item.get("quote") or "", combined, fuzzy_min)
                rows.append(_row(section, i, text, cites, item.get("quote"), ok, method, score,
                                 "" if ok else "quote unsupported by cited web source"))
                if not ok:
                    struck_texts.append(f"[web claim struck — quote unsupported] {text}")
                    continue
            else:
                rows.append(_row(section, i, text, cites, item.get("quote"), None, "unverified", None, ""))
            kept.append(item)
        pruned[section] = kept

    for name, a in (pruned.get("assessments") or {}).items():
        cites = a.get("citations", [])
        web_ids = _web_ids(cites)
        if web_ids:                                    # recorded + scored, but assessments are never struck
            n_web += 1
            combined = "\n".join(texts.get(w, "") for w in web_ids)
            ok, score, method = quote_supported(a.get("quote") or "", combined, fuzzy_min)
            note = "" if ok else "quote unsupported (assessment kept; cites should be table/doc)"
            rows.append(_row(f"assessment:{name}", 0, a.get("summary", ""), cites, a.get("quote"),
                             ok, method, score, note))
        else:
            rows.append(_row(f"assessment:{name}", 0, a.get("summary", ""), cites, a.get("quote"),
                             None, "unverified", None, ""))

    n_struck = len(struck_texts)
    if struck_texts:
        pruned["data_gaps"] = ((pruned.get("data_gaps") or []) + struck_texts)[:10]  # schema maxItems 10
    return pruned, rows, n_web, n_struck
