"""build_features(as_of): universe -> price + fundamental + valuation + cross-section -> features table."""
from __future__ import annotations

from datetime import date
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from ..store import upsert, table_columns
from ..store.pit import index_series
from ..spine.universe import build_universe, store_universe
from .fundamental import fundamental_features
from .panel import PricePanel, load_panel, window_start
from .price import price_features
from .xsection import bucket_scores


def build_features(con: duckdb.DuckDBPyConnection, as_of: date, panel: Optional[PricePanel] = None,
                   universe: Optional[pd.DataFrame] = None, store: bool = True,
                   min_turnover_inr: float = 1e7, with_fundamentals: bool = True) -> pd.DataFrame:
    if universe is None:
        universe = build_universe(con, as_of, min_turnover_inr=min_turnover_inr)
        if store:
            store_universe(con, universe)
    if universe.empty:
        return pd.DataFrame()
    syms = universe.symbol.tolist()
    if panel is None:
        panel = load_panel(con, window_start(as_of, 400), as_of, series=("EQ", "BE", "BZ"))
    pos = panel.pos(as_of)
    bench = index_series(con, "Nifty 500", end=as_of)
    bench_close = pd.Series(bench.close.values, index=pd.to_datetime(bench.trade_date)) if not bench.empty else None
    pf = price_features(panel, pos, bench_close)
    pf = pf.reindex(syms)
    inst = con.execute("SELECT symbol, face_value, industry, sector FROM instruments").df().set_index("symbol")
    face = inst.face_value.to_dict()
    if with_fundamentals:
        ff = fundamental_features(con, as_of, syms, face, pf["close"])
        feat = pf.join(ff, how="left")
    else:
        feat = pf.copy()
    feat["industry"] = inst.industry.reindex(feat.index)
    feat["industry"] = feat["industry"].fillna(inst.sector.reindex(feat.index)).fillna("UNKNOWN")
    groups = feat["industry"]
    feat = feat.join(bucket_scores(feat, groups))
    # exclusion flags visible on as_of
    sv = con.execute("""SELECT symbol, list_name, stage FROM surveillance
                        WHERE as_of = (SELECT max(as_of) FROM surveillance WHERE as_of <= ?)""", [as_of]).df()
    ban = {r[0] for r in con.execute("SELECT symbol FROM fo_ban WHERE as_of = ?", [as_of]).fetchall()}
    asm = set(sv[(sv.list_name.str.startswith("ASM")) & (sv.stage >= 2)].symbol) if not sv.empty else set()
    gsm = set(sv[sv.list_name == "GSM"].symbol) if not sv.empty else set()
    feat["in_asm"] = feat.index.isin(asm).astype(int)
    feat["in_gsm"] = feat.index.isin(gsm).astype(int)
    feat["in_fo_ban"] = feat.index.isin(ban).astype(int)
    feat["rankable"] = ((feat["buckets_known"] >= 2) & (feat["in_gsm"] == 0) & (feat["in_asm"] == 0)).astype(int)
    feat = feat.reset_index().rename(columns={"index": "symbol"})
    feat.insert(0, "as_of", as_of)
    # every schema column is always present: an input nobody has yet is NaN (UNKNOWN), never absent
    feat = feat.reindex(columns=table_columns(con, "features")).replace([np.inf, -np.inf], np.nan)
    if store and with_fundamentals:
        con.execute("DELETE FROM features WHERE as_of = ?", [as_of])
        upsert(con, "features", feat)
    return feat


def get_features(con: duckdb.DuckDBPyConnection, as_of: date, panel: Optional[PricePanel] = None,
                 with_fundamentals: bool = True, cache: bool = True,
                 min_turnover_inr: float = 1e7) -> pd.DataFrame:
    """Cached full features from the table when present (L sleeve), else computed.
    Price-only features (S sleeve) are never cached."""
    if with_fundamentals and cache:
        df = con.execute("SELECT * FROM features WHERE as_of = ?", [as_of]).df()
        if not df.empty:
            return df.set_index("symbol")
    feat = build_features(con, as_of, panel=panel, store=with_fundamentals and cache,
                          min_turnover_inr=min_turnover_inr, with_fundamentals=with_fundamentals)
    return feat.set_index("symbol") if not feat.empty else feat
