"""Filing documents: NSE announcement attachments and annual reports, downloaded to
data/docs/<symbol>/, text extracted with pypdf into a sidecar, metadata in `documents`."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from ..config import settings
from ..store import upsert
from ..spine.http import Http, NseApi
from ..spine.nse_api import classify_announcement, fetch_annual_reports

KEEP_KINDS = {"transcript", "presentation", "results", "annual_report", "rating"}


def _doc_id(symbol: str, url: str) -> str:
    return f"{symbol}-{hashlib.sha1(url.encode()).hexdigest()[:10]}"


def extract_text(pdf_path: Path, max_pages: int = 400) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        pages = []
        for i, page in enumerate(reader.pages[:max_pages]):
            try:
                pages.append(f"\n\n[[page {i + 1}]]\n" + (page.extract_text() or ""))
            except Exception:                        # noqa: BLE001 - a bad page is skipped, not fatal
                pages.append(f"\n\n[[page {i + 1}]]\n")
        return "".join(pages), len(reader.pages)
    except Exception as e:                            # noqa: BLE001
        return f"[extraction failed: {e}]", 0


def sync_symbol_documents(con: duckdb.DuckDBPyConnection, api: NseApi, symbol: str, max_docs: int = 12,
                          kinds: set[str] = KEEP_KINDS, log=None) -> dict:
    """Download the most recent filings of the kept kinds that are not yet stored."""
    s = settings()
    ann = con.execute("""SELECT symbol, ann_dt, subject, description, attachment_url FROM announcements
                         WHERE symbol = ? AND attachment_url IS NOT NULL ORDER BY ann_dt DESC LIMIT 400""", [symbol]).df()
    cands = []
    for r in ann.itertuples():
        kind = classify_announcement(r.subject, r.description)
        if kind in kinds and str(r.attachment_url).lower().endswith(".pdf"):
            cands.append({"symbol": symbol, "kind": kind, "url": r.attachment_url, "title": (r.description or r.subject)[:200],
                          "period": None, "visible_from": pd.Timestamp(r.ann_dt).date()})
    ar = fetch_annual_reports(api, symbol, log)
    for r in (ar.to_dict("records") if not ar.empty else []):
        cands.append({"symbol": symbol, "kind": "annual_report", "url": r["url"], "title": r["title"],
                      "period": r["period"], "visible_from": r["visible_from"]})
    have = {r[0] for r in con.execute("SELECT doc_id FROM documents WHERE symbol = ?", [symbol]).fetchall()}
    out = {"downloaded": 0, "skipped": 0, "failed": 0}
    per_kind: dict[str, int] = {}
    for c in cands:
        did = _doc_id(symbol, c["url"])
        k = c["kind"]
        per_kind[k] = per_kind.get(k, 0) + 1
        if did in have or per_kind[k] > (3 if k != "annual_report" else 2) or out["downloaded"] >= max_docs:
            out["skipped"] += 1
            continue
        res = api.get_bytes(c["url"], source="doc", key=did, raw_rel=None)
        if log:
            log(res)
        if not res.ok or not res.content:
            out["failed"] += 1
            continue
        d = s.docs_dir / symbol
        d.mkdir(parents=True, exist_ok=True)
        pdf = d / f"{did}.pdf"
        pdf.write_bytes(res.content)
        text, pages = extract_text(pdf)
        txt = d / f"{did}.txt"
        txt.write_text(text)
        row = {"doc_id": did, "symbol": symbol, "kind": k, "title": c["title"], "period": c["period"], "url": c["url"],
               "local_path": str(pdf), "text_path": str(txt), "sha256": hashlib.sha256(res.content).hexdigest(),
               "bytes": len(res.content), "pages": pages, "fetched_at": datetime.now(), "visible_from": c["visible_from"]}
        upsert(con, "documents", pd.DataFrame([row]))
        con.execute("UPDATE announcements SET doc_id = ? WHERE symbol = ? AND attachment_url = ?", [did, symbol, c["url"]])
        out["downloaded"] += 1
    return out


def document_excerpt(text_path: str, max_chars: int = 12000) -> str:
    p = Path(text_path)
    if not p.exists():
        return ""
    t = p.read_text(errors="replace")
    t = re.sub(r"[ \t]+", " ", t)
    return t[:max_chars] + ("\n[...truncated...]" if len(t) > max_chars else "")
