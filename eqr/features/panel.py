"""Wide price panel (trading days x symbols) with split adjustment applied once.
All rolling price features are computed here and sampled at as-of dates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import duckdb
import numpy as np
import pandas as pd


@dataclass
class PricePanel:
    dates: pd.DatetimeIndex
    close: pd.DataFrame          # adjusted
    open: pd.DataFrame           # adjusted
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame         # adjusted share count
    turnover: pd.DataFrame       # INR, unadjusted (cash is cash)
    deliv_pct: pd.DataFrame
    raw_close: pd.DataFrame
    prev_close: pd.DataFrame     # adjusted prev close (for ATR)

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    def pos(self, as_of: date) -> int:
        """Row position of the last trading day <= as_of."""
        idx = self.dates.searchsorted(pd.Timestamp(as_of), side="right") - 1
        if idx < 0:
            raise ValueError(f"no trading day on/before {as_of}")
        return int(idx)


def load_panel(con: duckdb.DuckDBPyConnection, start: date, end: date,
               series: tuple[str, ...] = ("EQ", "BE", "BZ"), symbols: Optional[list[str]] = None) -> PricePanel:
    """One column per symbol across series moves (EQ -> BE trade-for-trade -> EQ): the
    stock is the same stock; eligibility is decided elsewhere from the EQ series."""
    where = ["p.trade_date BETWEEN ? AND ?", "p.series IN (" + ",".join("?" * len(series)) + ")"]
    params: list = [start, end, *series]
    if symbols:
        where.append("p.symbol IN (" + ",".join("?" * len(symbols)) + ")")
        params += list(symbols)
    px = con.execute(f"""
        SELECT p.trade_date, p.symbol, p.prev_close, p.open, p.high, p.low, p.close, p.volume,
               p.turnover_inr, p.deliv_pct
        FROM prices_daily p WHERE {' AND '.join(where)}
        QUALIFY row_number() OVER (PARTITION BY p.trade_date, p.symbol
                                   ORDER BY CASE p.series WHEN 'EQ' THEN 0 WHEN 'BE' THEN 1 ELSE 2 END) = 1
    """, params).df()
    if px.empty:
        raise ValueError("empty price panel")
    px["trade_date"] = pd.to_datetime(px["trade_date"])
    fac = con.execute("SELECT symbol, ex_date, factor FROM adj_factors WHERE ex_date BETWEEN ? AND ?",
                      [start, end]).df()
    days = pd.DatetimeIndex(sorted(px["trade_date"].unique()))

    def wide(col):
        return px.pivot(index="trade_date", columns="symbol", values=col).reindex(days)

    raw_close = wide("close")
    cum = pd.DataFrame(1.0, index=days, columns=raw_close.columns)
    if not fac.empty:
        fac["ex_date"] = pd.to_datetime(fac["ex_date"])
        fac = fac[fac.symbol.isin(raw_close.columns)]
        f = fac.pivot_table(index="ex_date", columns="symbol", values="factor", aggfunc="prod")
        f = f.reindex(index=days, columns=raw_close.columns).fillna(1.0)
        # multiplier for date t = product of factors with ex_date > t
        cum = f.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
    close = raw_close * cum
    panel = PricePanel(
        dates=days, close=close, open=wide("open") * cum, high=wide("high") * cum,
        low=wide("low") * cum, volume=wide("volume") / cum, turnover=wide("turnover_inr"),
        deliv_pct=wide("deliv_pct"), raw_close=raw_close, prev_close=wide("prev_close") * cum,
    )
    return panel


def window_start(end: date, sessions: int = 400) -> date:
    """Calendar start that safely covers `sessions` trading days."""
    return end - timedelta(days=int(sessions * 1.55) + 10)
