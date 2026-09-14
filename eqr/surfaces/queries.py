"""Read-only queries shared by the web UI, the advisor API and the digest."""
from __future__ import annotations

import json
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


def latest_rating(con, symbol: str, engine_version: Optional[str] = None, variant: str = 'base') -> Optional[dict]:
    """Latest rating row for a symbol, with JSON columns parsed into dicts. Returns None if not found."""
    if engine_version is None:
        # Get the latest engine version available for this symbol
        row = con.execute("""SELECT symbol, as_of, engine_version, variant, status, rating, score, confidence,
                            confidence_band, coverage, pillars_json, gates_json, manifest_json, manifest_sha,
                            data_errors_json, decision_json, rule_id, profile, mos_base, fv_base, fv_bull, fv_bear,
                            dci_band, valuation_json, price, created_at
                            FROM ratings WHERE symbol = ? AND variant = ?
                            ORDER BY as_of DESC, engine_version DESC LIMIT 1""", [symbol, variant]).fetchone()
    else:
        row = con.execute("""SELECT symbol, as_of, engine_version, variant, status, rating, score, confidence,
                            confidence_band, coverage, pillars_json, gates_json, manifest_json, manifest_sha,
                            data_errors_json, decision_json, rule_id, profile, mos_base, fv_base, fv_bull, fv_bear,
                            dci_band, valuation_json, price, created_at
                            FROM ratings WHERE symbol = ? AND engine_version = ? AND variant = ?
                            ORDER BY as_of DESC LIMIT 1""", [symbol, engine_version, variant]).fetchone()
    if not row:
        return None
    return {
        "symbol": row[0], "as_of": row[1], "engine_version": row[2], "variant": row[3],
        "status": row[4], "rating": row[5], "score": row[6], "confidence": row[7],
        "confidence_band": row[8], "coverage": row[9],
        "pillars": json.loads(row[10]) if row[10] else {},
        "gates": json.loads(row[11]) if row[11] else [],
        "manifest": json.loads(row[12]) if row[12] else {},
        "manifest_sha": row[13],
        "data_errors": json.loads(row[14]) if row[14] else [],
        "decision": json.loads(row[15]) if row[15] else None,
        "rule_id": row[16], "profile": row[17],
        "mos_base": row[18], "fv_base": row[19], "fv_bull": row[20], "fv_bear": row[21],
        "dci_band": row[22],
        "valuation": json.loads(row[23]) if row[23] else {},
        "price": row[24], "created_at": row[25]
    }


def ratings_table(con, as_of: Optional[date] = None, engine_version: Optional[str] = None,
                  variant: str = 'base', verdict: Optional[str] = None,
                  profile: Optional[str] = None, limit: int = 2000) -> pd.DataFrame:
    """All ratings for a given as_of date, optionally filtered by verdict/profile.
    Returns sortable columns: symbol, rating, score, mos_base, confidence, dci_band, profile, rule_id, n_hard, n_soft, n_watch, as_of."""
    if as_of is None:
        as_of = con.execute("SELECT max(as_of) FROM ratings WHERE variant = ?", [variant]).fetchone()[0]
    if as_of is None:
        return pd.DataFrame()

    sql = """SELECT symbol, rating, score, mos_base, confidence, dci_band, profile, rule_id, as_of,
                    gates_json
             FROM ratings
             WHERE variant = ? AND as_of = ?"""
    params = [variant, as_of]

    if engine_version is not None:
        sql += " AND engine_version = ?"
        params.append(engine_version)
    if verdict is not None:
        sql += " AND rating = ?"
        params.append(verdict)
    if profile is not None:
        sql += " AND profile = ?"
        params.append(profile)

    sql += f" ORDER BY symbol LIMIT {limit}"
    df = con.execute(sql, params).df()

    # Parse JSON gate counts client-side
    def count_gates_by_tier(gates_json_str, tier):
        try:
            gates = json.loads(gates_json_str) if gates_json_str else []
            return sum(1 for g in gates if g.get("tier") == tier)
        except (json.JSONDecodeError, TypeError):
            return 0

    df["n_hard"] = df["gates_json"].apply(lambda x: count_gates_by_tier(x, "HARD"))
    df["n_soft"] = df["gates_json"].apply(lambda x: count_gates_by_tier(x, "SOFT"))
    df["n_watch"] = df["gates_json"].apply(lambda x: count_gates_by_tier(x, "WATCH"))
    df = df.drop("gates_json", axis=1)

    return df


def rating_history(con, symbol: str, limit: int = 24) -> pd.DataFrame:
    """Latest N ratings for a symbol, ordered by as_of descending."""
    return con.execute("""SELECT as_of, rating, score, mos_base, confidence, dci_band,
                         engine_version, variant, rule_id
                         FROM ratings WHERE symbol = ?
                         ORDER BY as_of DESC, engine_version DESC LIMIT ?""", [symbol, limit]).df()


def engine_claim_state(con, engine_version: str) -> str:
    """Return the claim state for an engine version: DIAGNOSTIC|PROVISIONAL|BACKTEST_PASS|VALIDATED.
    Reads from rating_calibrations; no calibration row returns DIAGNOSTIC."""
    from ..validate.claims import ClaimState
    row = con.execute("SELECT verdict FROM rating_calibrations WHERE engine_version = ? ORDER BY created_at DESC LIMIT 1",
                      [engine_version]).fetchone()
    if not row or not row[0]:
        return ClaimState.DIAGNOSTIC.value
    if row[0] == "VALIDATED":
        return ClaimState.PROVISIONAL.value  # PROVISIONAL until integrity items are closed
    return ClaimState.DIAGNOSTIC.value


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
    from ..validate.claims import claim_state, is_validated
    for sl in ("L", "S"):
        as_of = con.execute("SELECT max(as_of) FROM ranks WHERE sleeve = ?", [sl]).fetchone()[0]
        row = con.execute("SELECT rank, score, weight, universe_size FROM ranks WHERE sleeve = ? AND as_of = ? AND symbol = ?",
                          [sl, as_of, symbol]).fetchone() if as_of else None
        state, reasons = claim_state(con, sl)
        out[f"sleeve_{sl}"] = {"as_of": str(as_of) if as_of else None,
                               "rank": row[0] if row else None, "score": round(row[1], 4) if row else None,
                               "in_portfolio": bool(row and row[2] > 0), "universe_size": row[3] if row else None,
                               "percentile": round(1 - row[0] / row[3], 3) if row and row[3] else None,
                               "claim_state": state.value, "reasons": reasons, "validated": is_validated(state)}
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

    # Add decision block from latest rating
    rating = latest_rating(con, symbol)
    if rating and rating.get("decision"):
        dec = rating["decision"]
        claim_state_val = engine_claim_state(con, rating["engine_version"])
        out["decision"] = {
            "as_of": str(rating["as_of"]),
            "verdict": dec.get("verdict"),
            "rule_id": dec.get("rule_id"),
            "score": rating.get("score"),
            "mos": rating.get("mos_base"),
            "dci": rating.get("confidence"),
            "band": rating.get("dci_band"),
            "flags": [g.get("code") for g in rating.get("gates", [])],
            "claim_state": claim_state_val,
            "validated": claim_state_val in ("BACKTEST_PASS", "PROSPECTIVE_VALIDATED")
        }
    else:
        out["decision"] = None

    if out["freshness_days"] is None or out["as_of"] is None:
        out["status"] = "UNKNOWN"
    elif out["freshness_days"] > 40:
        out["status"] = "STALE"
    else:
        out["status"] = "OK"
    return out
