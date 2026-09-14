"""Point-in-time readers. Every strategy-facing read goes through these so a
fact is never used before its visible_from."""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd


def statements_as_of(con: duckdb.DuckDBPyConnection, as_of: date, symbols: list[str] | None = None,
                     stmt: str | None = None, basis: str | None = None) -> pd.DataFrame:
    """Long-format statements visible on `as_of` (visible_from <= as_of).
    Consolidated wins over standalone per (symbol, stmt, period_end, line_item)."""
    where = ["visible_from <= ?"]
    params: list = [as_of]
    if symbols:
        where.append("symbol IN (" + ",".join("?" * len(symbols)) + ")")
        params += list(symbols)
    if stmt:
        where.append("stmt = ?")
        params.append(stmt)
    if basis:
        where.append("basis = ?")
        params.append(basis)
    sql = f"""
        SELECT symbol, basis, stmt, period_end, line_item, value, visible_from
        FROM statements WHERE {' AND '.join(where)}
        QUALIFY row_number() OVER (PARTITION BY symbol, stmt, period_end, line_item
                                   ORDER BY CASE basis WHEN 'consolidated' THEN 0 ELSE 1 END) = 1
    """
    return con.execute(sql, params).df()


def shareholding_as_of(con: duckdb.DuckDBPyConnection, as_of: date,
                       symbols: list[str] | None = None) -> pd.DataFrame:
    where = ["visible_from <= ?"]
    params: list = [as_of]
    if symbols:
        where.append("symbol IN (" + ",".join("?" * len(symbols)) + ")")
        params += list(symbols)
    return con.execute(
        f"SELECT symbol, period_end, holder, pct FROM shareholding WHERE {' AND '.join(where)}",
        params).df()


def prices_window(con: duckdb.DuckDBPyConnection, end: date, sessions: int,
                  symbols: list[str] | None = None, series: tuple[str, ...] = ("EQ", "BE")) -> pd.DataFrame:
    """Last `sessions` trading days ending at `end` (inclusive), EQ/BE series, with
    split-adjusted close/open/high/low (adj_*) computed from adj_factors."""
    days = con.execute(
        "SELECT trade_date FROM trading_days WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT ?",
        [end, sessions]).fetchall()
    if not days:
        return pd.DataFrame()
    start = days[-1][0]
    where = ["p.trade_date BETWEEN ? AND ?", "p.series IN (" + ",".join("?" * len(series)) + ")"]
    params: list = [start, end, *series]
    if symbols:
        where.append("p.symbol IN (" + ",".join("?" * len(symbols)) + ")")
        params += list(symbols)
    sql = f"""
        WITH px AS (
          SELECT p.trade_date, p.symbol, p.series, p.prev_close, p.open, p.high, p.low, p.close,
                 p.vwap, p.volume, p.turnover_inr, p.trades, p.deliv_qty, p.deliv_pct
          FROM prices_daily p WHERE {' AND '.join(where)}
        ), fac AS (
          -- cumulative factor applying to dates BEFORE each ex_date; factor at/after ex_date is 1
          SELECT px.trade_date, px.symbol,
                 coalesce(exp(sum(ln(a.factor))), 1.0) AS cum_factor
          FROM px LEFT JOIN adj_factors a
            ON a.symbol = px.symbol AND a.ex_date > px.trade_date AND a.ex_date <= ?
          GROUP BY px.trade_date, px.symbol
        )
        SELECT px.*, fac.cum_factor,
               px.close * fac.cum_factor AS adj_close, px.open * fac.cum_factor AS adj_open,
               px.high * fac.cum_factor AS adj_high, px.low * fac.cum_factor AS adj_low,
               CASE WHEN fac.cum_factor > 0 THEN px.volume / fac.cum_factor ELSE px.volume END AS adj_volume
        FROM px JOIN fac USING (trade_date, symbol)
        ORDER BY px.symbol, px.trade_date
    """
    params.append(end)
    return con.execute(sql, params).df()


def index_series(con: duckdb.DuckDBPyConnection, index_name: str, end: date | None = None,
                 start: date | None = None) -> pd.DataFrame:
    where, params = ["index_name = ?"], [index_name]
    if start:
        where.append("trade_date >= ?"); params.append(start)
    if end:
        where.append("trade_date <= ?"); params.append(end)
    return con.execute(
        f"SELECT trade_date, close, pe, pb, div_yield FROM index_daily WHERE {' AND '.join(where)} "
        "ORDER BY trade_date", params).df()
