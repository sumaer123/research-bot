"""Prospective (forward-looking) ledger.

After the holdout was inspected, a backtest can no longer *prove* the strategy — only a
sealed, forward record can. Each month-end on or after a sleeve version's freeze date, publish
its held names with the signal-date close; once a horizon has elapsed, score fills the realised
forward return and the benchmark return. The report speaks only with >= 100 matured rows, and
any money-weighted return it quotes is XIRR-engine certified before it is stated ([[xirr-engine-agent]]).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import duckdb

from ..features.panel import load_panel, window_start
from ..store.pit import index_series

# Each engine version is its own hypothesis with its own freeze date (the first month-end it is
# published live). L-v1 is today's shipped sleeve L; L-v2, r1, r2, r3 get their own entries.
FREEZE = {"L-v1": date(2026, 9, 30)}
DEFAULT_HORIZON_DAYS = 252          # ~12 months; the binding constraint on saying "validated"
ENGINE_FOR_SLEEVE = {"L": "L-v1"}


def freeze_date(engine_version: str) -> Optional[date]:
    return FREEZE.get(engine_version)


def _is_month_end(con: duckdb.DuckDBPyConnection, as_of: date) -> bool:
    nxt = con.execute("SELECT min(trade_date) FROM trading_days WHERE trade_date > ?", [as_of]).fetchone()[0]
    return nxt is None or (nxt.year, nxt.month) != (as_of.year, as_of.month)


def publish(con: duckdb.DuckDBPyConnection, sleeve: str, engine_version: Optional[str] = None,
            as_of: Optional[date] = None, freeze: Optional[date] = None,
            horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict:
    """Snapshot a sleeve version's held names at a month-end on/after its freeze date. No-op before
    the freeze, off a month-end, or when that as_of was already published (append-only)."""
    engine_version = engine_version or ENGINE_FOR_SLEEVE.get(sleeve, f"{sleeve}-v1")
    freeze = freeze if freeze is not None else freeze_date(engine_version)
    if as_of is None:
        as_of = con.execute("SELECT max(as_of) FROM ranks WHERE sleeve = ?", [sleeve]).fetchone()[0]
    if as_of is None:
        return {"published": 0, "reason": "no ranks"}
    if freeze and as_of < freeze:
        return {"published": 0, "reason": f"before freeze {freeze}"}
    if not _is_month_end(con, as_of):
        return {"published": 0, "reason": "not a month-end session"}
    if con.execute("SELECT count(*) FROM prospective_ledger WHERE sleeve = ? AND engine_version = ? AND as_of = ?",
                   [sleeve, engine_version, as_of]).fetchone()[0]:
        return {"published": 0, "reason": "already published"}
    held = con.execute("SELECT symbol, rank, weight FROM ranks WHERE sleeve = ? AND as_of = ? AND weight > 0 ORDER BY rank",
                       [sleeve, as_of]).fetchall()
    if not held:
        return {"published": 0, "reason": "no held names"}
    closes = dict(con.execute("SELECT symbol, close FROM prices_daily WHERE trade_date = ? AND series = 'EQ' AND symbol IN "
                              "(" + ",".join("?" * len(held)) + ")", [as_of, *[h[0] for h in held]]).fetchall())
    now = datetime.now()
    for symbol, rank, weight in held:
        con.execute("INSERT INTO prospective_ledger (sleeve, engine_version, freeze_date, as_of, symbol, rank, weight, "
                    "close_at_signal, published_at, horizon_days, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                    [sleeve, engine_version, freeze, as_of, symbol, int(rank), float(weight),
                     closes.get(symbol), now, horizon_days])
    return {"published": len(held), "as_of": str(as_of), "engine_version": engine_version}


def _matured_session(con: duckdb.DuckDBPyConnection, as_of: date, horizon_days: int) -> Optional[date]:
    row = con.execute("SELECT trade_date FROM trading_days WHERE trade_date > ? ORDER BY trade_date LIMIT 1 OFFSET ?",
                      [as_of, horizon_days - 1]).fetchone()
    return row[0] if row else None


def score(con: duckdb.DuckDBPyConnection, sleeve: str, engine_version: Optional[str] = None,
          as_of_max: Optional[date] = None) -> dict:
    """Fill pending rows whose horizon has elapsed with realised and benchmark forward returns."""
    engine_version = engine_version or ENGINE_FOR_SLEEVE.get(sleeve, f"{sleeve}-v1")
    today = as_of_max or con.execute("SELECT max(trade_date) FROM trading_days").fetchone()[0]
    pending_dates = [r[0] for r in con.execute(
        "SELECT DISTINCT as_of FROM prospective_ledger WHERE sleeve = ? AND engine_version = ? AND outcome = 'pending' "
        "ORDER BY as_of", [sleeve, engine_version]).fetchall()]
    filled = 0
    for as_of in pending_dates:
        horizon = con.execute("SELECT max(horizon_days) FROM prospective_ledger WHERE sleeve = ? AND engine_version = ? "
                              "AND as_of = ?", [sleeve, engine_version, as_of]).fetchone()[0] or DEFAULT_HORIZON_DAYS
        matured = _matured_session(con, as_of, horizon)
        if not matured or matured > today:
            continue
        rows = con.execute("SELECT symbol FROM prospective_ledger WHERE sleeve = ? AND engine_version = ? AND as_of = ? "
                           "AND outcome = 'pending'", [sleeve, engine_version, as_of]).fetchall()
        syms = [r[0] for r in rows]
        panel = load_panel(con, window_start(as_of, 30), matured, symbols=syms)
        i0, i1 = panel.pos(as_of), panel.pos(matured)
        b = index_series(con, "Nifty 500", start=as_of, end=matured)
        bench_ret = float(b.close.iloc[-1] / b.close.iloc[0] - 1) if len(b) > 1 else None
        for symbol in syms:
            fwd = None
            if symbol in panel.close.columns:
                p0, p1 = panel.close[symbol].iloc[i0], panel.close[symbol].iloc[i1]
                if p0 and p0 > 0 and p1 == p1:                       # p1 == p1 rejects NaN
                    fwd = float(p1 / p0 - 1)
            if fwd is None:
                outcome = "delisted"
            elif bench_ret is None:
                outcome = "hit" if fwd > 0 else "miss"
            else:
                outcome = "hit" if fwd > bench_ret else "miss"
            con.execute("UPDATE prospective_ledger SET matured_at = ?, fwd_return = ?, bench_return = ?, outcome = ? "
                        "WHERE sleeve = ? AND engine_version = ? AND as_of = ? AND symbol = ?",
                        [matured, fwd, bench_ret, outcome, sleeve, engine_version, as_of, symbol])
            filled += 1
    return {"filled": filled, "engine_version": engine_version}


def report(con: duckdb.DuckDBPyConnection, sleeve: str, engine_version: Optional[str] = None,
           min_matured: int = 100) -> dict:
    """Portfolio forward excess and hit rate — only once >= min_matured rows have matured."""
    engine_version = engine_version or ENGINE_FOR_SLEEVE.get(sleeve, f"{sleeve}-v1")
    rows = con.execute("SELECT weight, fwd_return, bench_return FROM prospective_ledger WHERE sleeve = ? AND "
                       "engine_version = ? AND outcome IN ('hit', 'miss') AND fwd_return IS NOT NULL",
                       [sleeve, engine_version]).fetchall()
    n = len(rows)
    if n < min_matured:
        return {"status": "INSUFFICIENT", "matured": n, "need": min_matured, "engine_version": engine_version}
    wsum = sum(w for w, _, _ in rows) or 1.0
    port_fwd = sum(w * fr for w, fr, _ in rows) / wsum
    port_bench = sum(w * (br or 0.0) for w, _, br in rows) / wsum
    hit_rate = sum(1 for _, fr, br in rows if fr > (br or 0.0)) / n
    return {"status": "OK", "matured": n, "engine_version": engine_version,
            "portfolio_fwd_return": port_fwd, "portfolio_bench_return": port_bench,
            "portfolio_excess": port_fwd - port_bench, "hit_rate": hit_rate,
            "note": "money-weighted returns must be XIRR-engine certified before they are quoted"}
