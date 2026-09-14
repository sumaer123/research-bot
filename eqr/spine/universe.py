"""PIT liquidity-defined universe for an as-of date (no index membership, no survivorship)."""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from ..store import upsert


def build_universe(con: duckdb.DuckDBPyConnection, as_of: date, *, min_turnover_inr: float = 1e7,
                   min_history: int = 250, min_price: float = 20.0, window: int = 120,
                   min_sessions: int = 100) -> pd.DataFrame:
    sql = """
      WITH days AS (
        SELECT trade_date FROM trading_days WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT ?
      ), d20 AS (SELECT trade_date FROM days ORDER BY trade_date DESC LIMIT 20),
      w AS (
        SELECT p.symbol, p.trade_date, p.close, p.turnover_inr
        FROM prices_daily p JOIN days USING (trade_date) WHERE p.series = 'EQ'
      ),
      agg AS (
        SELECT symbol, median(turnover_inr) AS turnover_med120, count(*) AS n120,
               max(trade_date) AS last_dt
        FROM w GROUP BY symbol
      ),
      adv AS (
        SELECT symbol, avg(turnover_inr) AS adv20_inr FROM w
        WHERE trade_date >= (SELECT min(trade_date) FROM d20) GROUP BY symbol
      ),
      hist AS (
        SELECT symbol, count(*) AS history_days FROM prices_daily
        WHERE series = 'EQ' AND trade_date <= ? GROUP BY symbol
      ),
      lastpx AS (SELECT symbol, close FROM prices_daily WHERE trade_date = ? AND series = 'EQ')
      SELECT a.symbol, i.industry, l.close, adv.adv20_inr, a.turnover_med120, h.history_days
      FROM agg a JOIN lastpx l USING (symbol) JOIN adv USING (symbol) JOIN hist h USING (symbol)
      LEFT JOIN instruments i USING (symbol)
      WHERE a.n120 >= ? AND h.history_days >= ? AND l.close >= ? AND a.turnover_med120 >= ?
        AND a.symbol NOT IN (SELECT symbol FROM etf_list)          -- ETFs trade in the EQ series but are not companies
      ORDER BY a.turnover_med120 DESC
    """
    df = con.execute(sql, [as_of, window, as_of, as_of, min_sessions, min_history, min_price,
                           min_turnover_inr]).df()
    df.insert(0, "as_of", as_of)
    # exclusions visible on as_of: GSM, ASM stage >= 2, F&O ban
    excl = con.execute("""
        SELECT DISTINCT symbol FROM surveillance
        WHERE as_of = (SELECT max(as_of) FROM surveillance WHERE as_of <= ?)
          AND (list_name = 'GSM' OR stage >= 2)
        UNION SELECT symbol FROM fo_ban WHERE as_of = ?
    """, [as_of, as_of]).df()
    if not excl.empty:
        df = df[~df.symbol.isin(set(excl.symbol))]
    return df.reset_index(drop=True)


def store_universe(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    return upsert(con, "universe_monthly", df)


def month_end_sessions(con: duckdb.DuckDBPyConnection, start: date, end: date) -> list[date]:
    rows = con.execute("""
        SELECT max(trade_date) FROM trading_days WHERE trade_date BETWEEN ? AND ?
        GROUP BY date_trunc('month', trade_date) ORDER BY 1
    """, [start, end]).fetchall()
    return [r[0] for r in rows]


def week_end_sessions(con: duckdb.DuckDBPyConnection, start: date, end: date) -> list[date]:
    rows = con.execute("""
        SELECT max(trade_date) FROM trading_days WHERE trade_date BETWEEN ? AND ?
        GROUP BY date_trunc('week', trade_date) ORDER BY 1
    """, [start, end]).fetchall()
    return [r[0] for r in rows]
