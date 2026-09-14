"""Market regime from NIFTY 500 vs its 200-DMA and India VIX's 1-year percentile."""
from __future__ import annotations

from datetime import date
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from ..store import upsert
from ..store.pit import index_series

EXPOSURE = {"RISK_ON": 1.0, "NEUTRAL": 0.7, "RISK_OFF": 0.4}


def regime_table(con: duckdb.DuckDBPyConnection, end: Optional[date] = None) -> pd.DataFrame:
    n5 = index_series(con, "Nifty 500", end=end).set_index("trade_date")["close"]
    vix = index_series(con, "India VIX", end=end).set_index("trade_date")["close"]
    if n5.empty:
        return pd.DataFrame()
    df = pd.DataFrame({"nifty500": n5})
    df["dma200"] = df["nifty500"].rolling(200, min_periods=120).mean()
    df["vix"] = vix.reindex(df.index).ffill()
    df["vix_pct"] = df["vix"].rolling(250, min_periods=120).rank(pct=True)
    above = df["nifty500"] > df["dma200"]
    calm = df["vix_pct"] < 0.8
    reg = np.where(above & calm, "RISK_ON", np.where(~above & ~calm, "RISK_OFF", "NEUTRAL"))
    df["regime"] = reg
    df.loc[df["dma200"].isna(), "regime"] = "NEUTRAL"
    df["exposure"] = df["regime"].map(EXPOSURE)
    df.index.name = "trade_date"
    return df.reset_index()


def store_regime(con: duckdb.DuckDBPyConnection, end: Optional[date] = None) -> int:
    df = regime_table(con, end)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return upsert(con, "regime_daily", df)


def regime_at(reg: pd.DataFrame, as_of: date) -> tuple[str, float]:
    if reg is None or reg.empty:
        return "NEUTRAL", EXPOSURE["NEUTRAL"]
    r = reg[pd.to_datetime(reg.trade_date) <= pd.Timestamp(as_of)]
    if r.empty:
        return "NEUTRAL", EXPOSURE["NEUTRAL"]
    last = r.iloc[-1]
    return str(last.regime), float(last.exposure)
