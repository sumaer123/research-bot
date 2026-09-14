"""Dossier pack: everything Claude may cite, as JSON + text excerpts, every source tagged."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from ..config import settings
from ..store.pit import statements_as_of, shareholding_as_of
from .docstore import document_excerpt


def _records(df: pd.DataFrame, n: Optional[int] = None) -> list[dict]:
    if df is None or df.empty:
        return []
    d = df if n is None else df.head(n)
    return json.loads(d.to_json(orient="records", date_format="iso", date_unit="s"))


def build_pack(con: duckdb.DuckDBPyConnection, symbol: str, as_of: Optional[date] = None,
               max_docs: int = 4, excerpt_chars: int = 12000) -> dict:
    as_of = as_of or con.execute("SELECT max(trade_date) FROM trading_days").fetchone()[0]
    s = settings()
    inst = con.execute("SELECT * FROM instruments WHERE symbol = ?", [symbol]).df()
    meta = con.execute("SELECT * FROM screener_meta WHERE symbol = ?", [symbol]).df()
    feat_date = con.execute("SELECT max(as_of) FROM features WHERE as_of <= ?", [as_of]).fetchone()[0]
    feat = con.execute("SELECT * FROM features WHERE symbol = ? AND as_of = ?", [symbol, feat_date]).df() if feat_date else pd.DataFrame()
    ranks = con.execute("""SELECT as_of, sleeve, rank, score, weight, regime, universe_size FROM ranks
                           WHERE symbol = ? AND as_of <= ? ORDER BY as_of DESC LIMIT 6""", [symbol, as_of]).df()
    px = con.execute("""SELECT trade_date, close, volume, deliv_pct, turnover_inr FROM prices_daily
                        WHERE symbol = ? AND series = 'EQ' AND trade_date <= ? ORDER BY trade_date DESC LIMIT 260""",
                     [symbol, as_of]).df()
    stmts = statements_as_of(con, as_of, [symbol])
    q = stmts[stmts.stmt == "pl_q"].pivot_table(index="period_end", columns="line_item", values="value").sort_index().tail(8)
    a = stmts[stmts.stmt.isin(["pl_a", "bs_a", "cf_a", "ratios_a"])]
    a_piv = a.pivot_table(index="period_end", columns="line_item", values="value").sort_index().tail(5)
    sh = shareholding_as_of(con, as_of, [symbol]).sort_values("period_end").tail(24)
    sv = con.execute("SELECT as_of, list_name, stage FROM surveillance WHERE symbol = ? AND as_of <= ? ORDER BY as_of DESC LIMIT 10",
                     [symbol, as_of]).df()
    deals = con.execute("SELECT trade_date, kind, client, side, qty, price FROM deals WHERE symbol = ? AND trade_date <= ? ORDER BY trade_date DESC LIMIT 20",
                        [symbol, as_of]).df()
    ann = con.execute("""SELECT ann_dt, subject, description, doc_id FROM announcements
                         WHERE symbol = ? AND ann_dt <= ? ORDER BY ann_dt DESC LIMIT 40""", [symbol, as_of]).df()
    ca = con.execute("SELECT ex_date, subject FROM corporate_actions WHERE symbol = ? AND ex_date <= ? ORDER BY ex_date DESC LIMIT 15",
                     [symbol, as_of]).df()
    rc = con.execute("""SELECT period_end, filing_dt, consolidated, audited FROM results_calendar
                        WHERE symbol = ? AND filing_dt <= ? ORDER BY period_end DESC LIMIT 8""", [symbol, as_of]).df()
    industry = inst.industry.iloc[0] if len(inst) and pd.notna(inst.industry.iloc[0]) else None
    peers = pd.DataFrame()
    if industry and feat_date:
        peers = con.execute("""SELECT symbol, mcap_cr, pe_ttm, pb, roe, roce, sales_yoy_ttm, pat_yoy_ttm, mom_12_1, z_quality, z_value, z_momentum
                               FROM features WHERE as_of = ? AND industry = ? AND symbol != ? ORDER BY mcap_cr DESC NULLS LAST LIMIT 8""",
                            [feat_date, industry, symbol]).df()
    regime = con.execute("SELECT trade_date, regime, exposure, nifty500, vix FROM regime_daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 1",
                         [as_of]).df()
    docs = con.execute("""SELECT doc_id, kind, title, period, visible_from, text_path, pages FROM documents
                          WHERE symbol = ? AND visible_from <= ? ORDER BY visible_from DESC""", [symbol, as_of]).df()
    # most useful first: transcripts, annual report, presentation, results; skip empty extractions
    prio = {"transcript": 0, "annual_report": 1, "presentation": 2, "results": 3, "rating": 4, "other": 5}
    docs = docs[docs.pages.fillna(0) >= 2].copy()
    docs["prio"] = docs.kind.map(prio).fillna(9)
    docs = docs.sort_values(["prio", "visible_from"], ascending=[True, False])
    chosen, seen_kind = [], {}
    for r in docs.itertuples():
        seen_kind[r.kind] = seen_kind.get(r.kind, 0) + 1
        if seen_kind[r.kind] <= (2 if r.kind in ("transcript", "results") else 1) and len(chosen) < max_docs:
            chosen.append(r)
    excerpts = [{"doc_id": r.doc_id, "kind": r.kind, "title": r.title, "period": r.period,
                 "visible_from": str(pd.Timestamp(r.visible_from).date()), "pages": int(r.pages or 0),
                 "text": document_excerpt(r.text_path, excerpt_chars)} for r in chosen]
    pack = {
        "symbol": symbol, "as_of": str(as_of), "feature_date": str(feat_date) if feat_date else None,
        # current instrument + screener snapshot — NOT point-in-time until instrument_as_of (Wave 2)
        "company_snapshot_current": {"pit": False, "instrument": _records(inst)[:1], "screener_meta": _records(meta)[:1]},
        "features": _records(feat)[:1], "ranks": _records(ranks),
        "prices_recent": _records(px.head(30)), "price_52w": {
            "high": float(px.close.max()) if len(px) else None, "low": float(px.close.min()) if len(px) else None,
            "last": float(px.close.iloc[0]) if len(px) else None,
            "return_12m": float(px.close.iloc[0] / px.close.iloc[-1] - 1) if len(px) > 200 else None},
        "quarterly": json.loads(q.to_json(orient="index", date_format="iso")) if len(q) else {},
        "annual": json.loads(a_piv.to_json(orient="index", date_format="iso")) if len(a_piv) else {},
        "shareholding": _records(sh), "surveillance": _records(sv), "deals": _records(deals),
        "announcements": _records(ann), "corporate_actions": _records(ca), "results_calendar": _records(rc),
        "peers": _records(peers), "regime": _records(regime)[:1],
        "documents": [{k: v for k, v in e.items() if k != "text"} for e in excerpts],
        "excerpts": excerpts,
        "citation_rules": "Cite doc:<doc_id> (optionally #p<page>) for anything taken from a document excerpt and "
                          "table:<name> for anything from the JSON tables (prices, features, ranks, statements, "
                          "shareholding, surveillance, deals, announcements, peers, regime, corporate_actions, results_calendar).",
    }
    out = s.packs_dir / f"{symbol}_{as_of}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "pack.json").write_text(json.dumps(pack, indent=1, default=str))
    pack["_path"] = str(out)
    return pack
