"""Read-only queries shared by the web UI, the advisor API and the digest."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import duckdb
import pandas as pd

from ..store import connect


def open_ro() -> duckdb.DuckDBPyConnection:
    return connect(read_only=True)


def freshness(con) -> dict:
    row = con.execute("SELECT max(trade_date), count(*) FROM trading_days").fetchone()
    feat = con.execute("SELECT max(as_of), count(DISTINCT as_of) FROM features").fetchone()
    stm = con.execute("SELECT max(fetched_at), count(DISTINCT symbol) FROM statements").fetchone()
    runs = con.execute("SELECT run_id, kind, started_at, ended_at, status, detail FROM runs ORDER BY started_at DESC LIMIT 8").df()
    qc = con.execute("""SELECT check_name, status, detail, as_of FROM quality_checks
                        WHERE run_id = (SELECT run_id FROM quality_checks ORDER BY checked_at DESC LIMIT 1)""").df()
    return {"last_session": row[0], "sessions": row[1], "last_features": feat[0], "feature_dates": feat[1],
            "statements_fetched_at": stm[0], "statements_symbols": stm[1], "runs": runs, "quality": qc,
            "session_age_days": (date.today() - row[0]).days if row[0] else None}


def regime_now(con) -> Optional[dict]:
    df = con.execute("SELECT * FROM regime_daily ORDER BY trade_date DESC LIMIT 1").df()
    return df.iloc[0].to_dict() if len(df) else None


def latest_ranks(con, sleeve: str, as_of: Optional[date] = None, held_only: bool = True) -> pd.DataFrame:
    if as_of is None:
        as_of = con.execute("SELECT max(as_of) FROM ranks WHERE sleeve = ?", [sleeve]).fetchone()[0]
    if as_of is None:
        return pd.DataFrame()
    sql = """SELECT r.as_of, r.rank, r.symbol, i.name, i.industry, r.score, r.weight, r.regime, r.universe_size,
                    f.close, f.mcap_cr, f.pe_ttm, f.mom_12_1, f.z_quality, f.z_value, f.z_momentum, f.z_lowrisk
             FROM ranks r LEFT JOIN instruments i USING (symbol)
             LEFT JOIN features f ON f.symbol = r.symbol AND f.as_of = (SELECT max(as_of) FROM features WHERE as_of <= r.as_of)
             WHERE r.sleeve = ? AND r.as_of = ? {held} ORDER BY r.rank"""
    return con.execute(sql.format(held="AND r.weight > 0" if held_only else "AND r.rank <= 100"), [sleeve, as_of]).df()


def rank_changes(con, sleeve: str) -> dict:
    dates = [r[0] for r in con.execute("SELECT DISTINCT as_of FROM ranks WHERE sleeve = ? ORDER BY as_of DESC LIMIT 2", [sleeve]).fetchall()]
    if len(dates) < 2:
        return {"entries": [], "exits": [], "as_of": dates[0] if dates else None}
    now = set(r[0] for r in con.execute("SELECT symbol FROM ranks WHERE sleeve = ? AND as_of = ? AND weight > 0", [sleeve, dates[0]]).fetchall())
    prev = set(r[0] for r in con.execute("SELECT symbol FROM ranks WHERE sleeve = ? AND as_of = ? AND weight > 0", [sleeve, dates[1]]).fetchall())
    return {"entries": sorted(now - prev), "exits": sorted(prev - now), "as_of": dates[0], "prev": dates[1]}


def symbol_page(con, symbol: str) -> dict:
    inst = con.execute("SELECT * FROM instruments WHERE symbol = ?", [symbol]).df()
    meta = con.execute("SELECT * FROM screener_meta WHERE symbol = ?", [symbol]).df()
    feat = con.execute("SELECT * FROM features WHERE symbol = ? ORDER BY as_of DESC LIMIT 1", [symbol]).df()
    ranks = con.execute("SELECT as_of, sleeve, rank, score, weight, regime, universe_size FROM ranks WHERE symbol = ? ORDER BY as_of DESC LIMIT 12", [symbol]).df()
    px = con.execute("""SELECT trade_date, close, prev_close, volume, deliv_pct FROM prices_daily
                        WHERE symbol = ? AND series IN ('EQ','BE') ORDER BY trade_date DESC LIMIT 260""", [symbol]).df().sort_values("trade_date")
    fac = con.execute("SELECT ex_date, factor, kind FROM adj_factors WHERE symbol = ? ORDER BY ex_date", [symbol]).df()
    stm = con.execute("SELECT stmt, period_end, line_item, value, visible_from FROM statements WHERE symbol = ? "
                      "QUALIFY row_number() OVER (PARTITION BY stmt, period_end, line_item ORDER BY CASE basis WHEN 'consolidated' THEN 0 ELSE 1 END) = 1",
                      [symbol]).df()
    q = stm[stm.stmt == "pl_q"].pivot_table(index="line_item", columns="period_end", values="value").iloc[:, -8:] if len(stm) else pd.DataFrame()
    a = stm[stm.stmt.isin(["pl_a", "bs_a", "cf_a", "ratios_a"])]
    a = a.pivot_table(index=["stmt", "line_item"], columns="period_end", values="value").iloc[:, -6:] if len(a) else pd.DataFrame()
    sh = con.execute("SELECT period_end, holder, pct FROM shareholding WHERE symbol = ? ORDER BY period_end", [symbol]).df()
    sh = sh.pivot_table(index="holder", columns="period_end", values="pct").iloc[:, -8:] if len(sh) else pd.DataFrame()
    dos = con.execute("SELECT as_of, model, rating, confidence, markdown FROM dossiers_current WHERE symbol = ? ORDER BY as_of DESC LIMIT 1", [symbol]).df()
    docs = con.execute("SELECT doc_id, kind, title, period, visible_from, pages FROM documents WHERE symbol = ? ORDER BY visible_from DESC LIMIT 20", [symbol]).df()
    ann = con.execute("SELECT ann_dt, subject, description FROM announcements WHERE symbol = ? ORDER BY ann_dt DESC LIMIT 15", [symbol]).df()
    sv = con.execute("SELECT as_of, list_name, stage FROM surveillance WHERE symbol = ? ORDER BY as_of DESC LIMIT 5", [symbol]).df()
    return {"symbol": symbol, "inst": inst.iloc[0].to_dict() if len(inst) else {}, "meta": meta.iloc[0].to_dict() if len(meta) else {},
            "feat": feat.iloc[0].to_dict() if len(feat) else {}, "ranks": ranks, "px": px, "factors": fac,
            "quarterly": q, "annual": a, "shareholding": sh, "dossier": dos.iloc[0].to_dict() if len(dos) else None,
            "documents": docs, "announcements": ann, "surveillance": sv}


def price_svg(px: pd.DataFrame, fac: pd.DataFrame, width: int = 760, height: int = 220) -> str:
    """Inline SVG line chart of the split-adjusted close (1y), no JS."""
    if px is None or len(px) < 5:
        return ""
    px = px.copy()
    px["trade_date"] = pd.to_datetime(px["trade_date"])
    mult = pd.Series(1.0, index=px.index)
    if fac is not None and len(fac):
        for r in fac.itertuples():
            mult[px["trade_date"] < pd.Timestamp(r.ex_date)] *= float(r.factor)
    y = (px["close"] * mult).to_numpy()
    lo, hi = float(y.min()), float(y.max())
    span = (hi - lo) or 1.0
    pts = []
    for i, v in enumerate(y):
        x = 40 + i / max(1, len(y) - 1) * (width - 50)
        yy = 10 + (hi - v) / span * (height - 30)
        pts.append(f"{x:.1f},{yy:.1f}")
    first, last = px["trade_date"].iloc[0].date(), px["trade_date"].iloc[-1].date()
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="adjusted close">'
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/>'
            f'<polyline fill="none" stroke="#1f6feb" stroke-width="1.6" points="{" ".join(pts)}"/>'
            f'<text x="2" y="14" font-size="11" fill="#555">{hi:,.1f}</text>'
            f'<text x="2" y="{height - 12}" font-size="11" fill="#555">{lo:,.1f}</text>'
            f'<text x="40" y="{height - 2}" font-size="11" fill="#555">{first}</text>'
            f'<text x="{width - 90}" y="{height - 2}" font-size="11" fill="#555">{last}</text></svg>')


def backtests(con) -> pd.DataFrame:
    return con.execute("SELECT run_id, sleeve, start_date, end_date, verdict, created_at, report_path FROM backtests ORDER BY created_at DESC LIMIT 50").df()


def advisor_evidence(con, symbol: str) -> dict:
    inst = con.execute("SELECT name, industry FROM instruments WHERE symbol = ?", [symbol]).fetchone()
    if not inst:
        return {"symbol": symbol, "status": "UNKNOWN", "reason": "symbol not in instruments"}
    fr = freshness(con)
    out = {"symbol": symbol, "name": inst[0], "industry": inst[1], "as_of": str(fr["last_features"]) if fr["last_features"] else None,
           "freshness_days": (date.today() - fr["last_features"]).days if fr["last_features"] else None, "flags": [], "regime": None}
    reg = regime_now(con)
    if reg:
        out["regime"] = {"label": reg["regime"], "exposure": reg["exposure"], "date": str(reg["trade_date"])}
    for sl in ("L", "S"):
        as_of = con.execute("SELECT max(as_of) FROM ranks WHERE sleeve = ?", [sl]).fetchone()[0]
        row = con.execute("SELECT rank, score, weight, universe_size FROM ranks WHERE sleeve = ? AND as_of = ? AND symbol = ?",
                          [sl, as_of, symbol]).fetchone() if as_of else None
        verdict = con.execute("SELECT verdict FROM backtests WHERE sleeve = ? AND verdict IN ('VALIDATED','NOT VALIDATED') ORDER BY created_at DESC LIMIT 1", [sl]).fetchone()
        out[f"sleeve_{sl}"] = {"as_of": str(as_of) if as_of else None,
                               "rank": row[0] if row else None, "score": round(row[1], 4) if row else None,
                               "in_portfolio": bool(row and row[2] > 0), "universe_size": row[3] if row else None,
                               "percentile": round(1 - row[0] / row[3], 3) if row and row[3] else None,
                               "validated": (verdict[0] == "VALIDATED") if verdict else False}
    f = con.execute("SELECT in_asm, in_gsm, in_fo_ban, altman_zpp, promoter_chg_1y, stmt_age_days, rankable FROM features WHERE symbol = ? ORDER BY as_of DESC LIMIT 1", [symbol]).fetchone()
    if f:
        if f[0]:
            out["flags"].append("ASM_STAGE_2_PLUS")
        if f[1]:
            out["flags"].append("GSM")
        if f[2]:
            out["flags"].append("FO_BAN")
        if f[3] is not None and f[3] < 1.1:
            out["flags"].append("ALTMAN_DISTRESS")
        if f[4] is not None and f[4] < -2:
            out["flags"].append("PROMOTER_SELLING")
        if f[5] is not None and f[5] > 200:
            out["flags"].append("STALE_STATEMENTS")
        if not f[6]:
            out["flags"].append("NOT_RANKABLE")
    d = con.execute("SELECT as_of, rating, confidence FROM dossiers_current WHERE symbol = ? ORDER BY as_of DESC LIMIT 1", [symbol]).fetchone()
    out["dossier"] = {"as_of": str(d[0]), "rating": d[1], "confidence": d[2]} if d else None
    if out["freshness_days"] is None or out["as_of"] is None:
        out["status"] = "UNKNOWN"
    elif out["freshness_days"] > 40:
        out["status"] = "STALE"
    else:
        out["status"] = "OK"
    return out
