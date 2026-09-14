"""Append-only rating ledger (the prospective arbiter for the engine) + maturity scoring.

Mirrors eqr/validate/prospective.py: publish once per (symbol, as_of, engine_version), never
rewrite a row, mature at the horizon with adjusted closes and a 1% delisting haircut."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import duckdb

from ..features.panel import load_panel, window_start
from ..store.pit import index_series

DEFAULT_HORIZON_DAYS = 252
DELIST_HAIRCUT = 0.01
PUBLISHED_VARIANT = "base"                 # only the default variant is ever published


def publish(con: duckdb.DuckDBPyConnection, as_of: date, engine_version: str,
            horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict:
    """Copy the RATED `base` rows for (as_of, engine_version) into the ledger; no-op for rows already there."""
    rows = con.execute("""SELECT r.symbol, r.rating, r.score, r.confidence, r.mos_base, r.price
                          FROM ratings r LEFT JOIN rating_ledger l
                            ON l.symbol = r.symbol AND l.as_of = r.as_of AND l.engine_version = r.engine_version
                          WHERE r.as_of = ? AND r.engine_version = ? AND r.variant = ? AND r.status = 'RATED'
                            AND l.symbol IS NULL""", [as_of, engine_version, PUBLISHED_VARIANT]).fetchall()
    if not rows:
        return {"published": 0, "as_of": str(as_of), "engine_version": engine_version, "reason": "nothing new"}
    prev = {r[0]: r[1] for r in con.execute(
        """SELECT symbol, rating FROM rating_ledger WHERE engine_version = ?
           AND as_of = (SELECT max(as_of) FROM rating_ledger WHERE engine_version = ? AND as_of < ?)""",
        [engine_version, engine_version, as_of]).fetchall()}
    now = datetime.now()
    con.executemany(
        "INSERT INTO rating_ledger (symbol, as_of, engine_version, published_at, rating, score, confidence, "
        "close_at_publish, horizon_days, outcome, mos_at_publish, dci_at_publish, verdict_prev) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
        [[s, as_of, engine_version, now, rating, score, conf, price, horizon_days, mos, conf, prev.get(s)]
         for s, rating, score, conf, mos, price in rows])
    return {"published": len(rows), "as_of": str(as_of), "engine_version": engine_version}


def _matured_session(con: duckdb.DuckDBPyConnection, as_of: date, horizon_days: int) -> Optional[date]:
    row = con.execute("SELECT trade_date FROM trading_days WHERE trade_date > ? ORDER BY trade_date LIMIT 1 OFFSET ?",
                      [as_of, horizon_days - 1]).fetchone()
    return row[0] if row else None


def mature(con: duckdb.DuckDBPyConnection, engine_version: str, today: Optional[date] = None) -> dict:
    """Fill pending rows whose horizon has elapsed: adjusted forward return, benchmark return,
    outcome hit/miss (vs benchmark) or delisted (last close x (1 - haircut))."""
    today = today or con.execute("SELECT max(trade_date) FROM trading_days").fetchone()[0]
    dates = [r[0] for r in con.execute("SELECT DISTINCT as_of FROM rating_ledger WHERE engine_version = ? "
                                       "AND outcome = 'pending' ORDER BY as_of", [engine_version]).fetchall()]
    filled = 0
    for as_of in dates:
        horizon = con.execute("SELECT max(horizon_days) FROM rating_ledger WHERE engine_version = ? AND as_of = ?",
                              [engine_version, as_of]).fetchone()[0] or DEFAULT_HORIZON_DAYS
        matured = _matured_session(con, as_of, horizon)
        if not matured or matured > today:
            continue
        syms = [r[0] for r in con.execute("SELECT symbol FROM rating_ledger WHERE engine_version = ? AND as_of = ? "
                                          "AND outcome = 'pending'", [engine_version, as_of]).fetchall()]
        panel = load_panel(con, window_start(as_of, 30), matured, symbols=syms)
        i0, i1 = panel.pos(as_of), panel.pos(matured)
        b = index_series(con, "Nifty 500", start=as_of, end=matured)
        bench = float(b.close.iloc[-1] / b.close.iloc[0] - 1) if len(b) > 1 else None
        for s in syms:
            fwd, outcome = None, "delisted"
            if s in panel.close.columns:
                col = panel.close[s]
                p0, p1 = col.iloc[i0], col.iloc[i1]
                if p0 and p0 > 0:
                    if p1 == p1:
                        fwd = float(p1 / p0 - 1)
                        outcome = "hit" if (fwd > (bench if bench is not None else 0.0)) else "miss"
                    else:
                        last = col.dropna()
                        if len(last):
                            fwd = float(last.iloc[-1] * (1 - DELIST_HAIRCUT) / p0 - 1)
            excess = None if fwd is None or bench is None else fwd - bench
            con.execute("UPDATE rating_ledger SET matured_at = ?, fwd_return = ?, bench_return = ?, excess_return = ?, "
                        "outcome = ? WHERE engine_version = ? AND as_of = ? AND symbol = ?",
                        [matured, fwd, bench, excess, outcome, engine_version, as_of, s])
            filled += 1
    return {"filled": filled, "engine_version": engine_version}


def latest_rating(con: duckdb.DuckDBPyConnection, symbol: str, engine_version: Optional[str] = None,
                  variant: str = PUBLISHED_VARIANT) -> Optional[dict]:
    where, params = ["symbol = ?", "variant = ?"], [symbol, variant]
    if engine_version:
        where.append("engine_version = ?"); params.append(engine_version)
    df = con.execute(f"SELECT * FROM ratings WHERE {' AND '.join(where)} ORDER BY as_of DESC LIMIT 1", params).df()
    return None if df.empty else df.iloc[0].to_dict()


def verdict_history(con: duckdb.DuckDBPyConnection, symbol: str, engine_version: Optional[str] = None,
                    limit: int = 24) -> list[dict]:
    where, params = ["symbol = ?", "variant = ?"], [symbol, PUBLISHED_VARIANT]
    if engine_version:
        where.append("engine_version = ?"); params.append(engine_version)
    return con.execute(f"SELECT as_of, engine_version, rating, score, confidence, mos_base, rule_id FROM ratings "
                       f"WHERE {' AND '.join(where)} ORDER BY as_of DESC LIMIT {int(limit)}", params).df().to_dict("records")


def report(con: duckdb.DuckDBPyConnection, engine_version: str, min_matured: int = 100, min_per_tier: int = 20) -> dict:
    """Prospective tier statistics — quoted only with >= min_matured rows and >= min_per_tier per tier."""
    df = con.execute("SELECT rating, fwd_return, bench_return, excess_return, outcome FROM rating_ledger "
                     "WHERE engine_version = ? AND outcome IN ('hit','miss','delisted') AND fwd_return IS NOT NULL",
                     [engine_version]).df()
    n = len(df)
    if n < min_matured:
        return {"status": "INSUFFICIENT", "matured": n, "need": min_matured, "engine_version": engine_version}
    tiers = {}
    for tier, g in df.groupby("rating"):
        tiers[tier] = {"n": int(len(g)), "mean_excess": float(g.excess_return.mean()) if g.excess_return.notna().any() else None,
                       "hit_rate": float((g.excess_return > 0).mean()) if g.excess_return.notna().any() else None,
                       "quotable": bool(len(g) >= min_per_tier)}
    return {"status": "OK", "matured": n, "engine_version": engine_version, "tiers": tiers,
            "note": "time-weighted per-name returns; any money-weighted figure must be XIRR-engine certified"}
