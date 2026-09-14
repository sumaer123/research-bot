"""Produce and store a sleeve's ranked list for an as-of date."""
from __future__ import annotations

from datetime import date
from typing import Optional

import duckdb
import pandas as pd

from ..store import upsert
from .regime import regime_table, regime_at
from .sizing import inverse_vol_weights
from .sleeves import SleeveConfig, score, select, rank_table


def rank_sleeve(con: duckdb.DuckDBPyConnection, cfg: SleeveConfig, as_of: date,
                feat: Optional[pd.DataFrame] = None, prev: Optional[list[str]] = None,
                store: bool = True) -> pd.DataFrame:
    if feat is None:
        feat = con.execute("SELECT * FROM features WHERE as_of = ?", [as_of]).df().set_index("symbol")
    if feat.empty:
        return pd.DataFrame()
    reg = regime_table(con, end=as_of)
    regime, exposure = regime_at(reg, as_of)
    if prev is None:
        prev_rows = con.execute("""SELECT symbol FROM ranks WHERE sleeve = ? AND weight > 0
                                   AND as_of = (SELECT max(as_of) FROM ranks WHERE sleeve = ? AND as_of < ?)""",
                                [cfg.name, cfg.name, as_of]).fetchall()
        prev = [r[0] for r in prev_rows]
    sc = score(feat, cfg)
    allow_new = not (cfg.regime_gate and regime == "RISK_OFF")
    chosen = select(sc, prev, cfg, allow_new=allow_new)
    w = inverse_vol_weights(chosen, feat["vol_60"], feat["industry"], exposure, cfg.cap_name, cfg.cap_industry)
    tbl = rank_table(sc)
    tbl["weight"] = tbl["symbol"].map(w).fillna(0.0)
    tbl.insert(0, "as_of", as_of)
    tbl.insert(1, "sleeve", cfg.name)
    tbl["regime"] = regime
    tbl["universe_size"] = int(sc.notna().sum())
    tbl["detail"] = cfg.variant
    if store:
        con.execute("DELETE FROM ranks WHERE as_of = ? AND sleeve = ?", [as_of, cfg.name])
        upsert(con, "ranks", tbl)
    return tbl
