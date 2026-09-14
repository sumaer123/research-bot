"""build_metrics(as_of): point-in-time inputs -> every pillar module -> `fund_metrics` (long, PIT).

Order matters only for the two cross-module edges: valuation needs growth's
`fundamental_growth` and moat/solvency's `wacc` / `net_debt`; `growth_gap` is derived here
from valuation's `implied_growth` minus growth's `fundamental_growth`."""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from ..store import upsert
from .base import Inputs, MetricSet, load_inputs, ok, unknown

log = logging.getLogger("eqr.fundamentals")

METRICS_VERSION = "m1"


def compute_all(inp: Inputs) -> MetricSet:
    """Every fundamentals module for one name; pure apart from the modules' own arithmetic."""
    from . import moat, solvency, forensic, growth, management, valuation, sector_kpis
    ms = MetricSet()
    ms.extend(moat.compute(inp))
    ms.extend(solvency.compute(inp, ctx={"wacc": ms.v("wacc")}))
    ms.extend(forensic.compute(inp))
    ms.extend(growth.compute(inp))
    ms.extend(valuation.compute(inp, ctx={"fundamental_growth": ms.v("fundamental_growth"),
                                          "net_debt": ms.v("net_debt"), "wacc": ms.v("wacc"),
                                          "nopat_ttm": ms.v("nopat_ttm")}))
    ms.extend(management.compute(inp, ctx={"net_debt_ebitda": ms.v("net_debt_ebitda")}))
    ms.extend(sector_kpis.compute(inp))
    ig, fg = ms.v("implied_growth"), ms.v("fundamental_growth")
    if ig is not None and fg is not None and not inp.is_financial:
        ms.add(ok("growth_gap", ig - fg, note="implied_growth - fundamental_growth"))
        ms.add(ok("growth_gap_val", ig - fg, note="same as growth_gap (valuation pillar view)"))
    elif inp.is_financial:
        from .base import na
        ms.add(na("growth_gap")); ms.add(na("growth_gap_val"))
    else:
        ms.add(unknown("growth_gap", "implied or fundamental growth unknown"))
        ms.add(unknown("growth_gap_val", "implied or fundamental growth unknown"))
    # context carried for the engine (not scored)
    ms.add(ok("stmt_age_days", inp.feat.get("stmt_age_days"), unit="days", source_table="features"))
    ms.add(ok("history_days", inp.feat.get("history_days"), unit="days", source_table="features"))
    ms.add(ok("pe_ttm_feat", inp.feat.get("pe_ttm"), source_table="features"))
    ms.add(ok("pat_ttm", inp.ttm("net_profit"), unit="crore"))
    return ms


def build_metrics(con: duckdb.DuckDBPyConnection, as_of: date, symbols: Optional[list[str]] = None,
                  store: bool = True, with_xbrl: bool = True) -> pd.DataFrame:
    """Compute and (optionally) store the fund_metrics slice for as_of. Returns the wide frame
    (index symbol, columns metric values; NaN = UNKNOWN/NA) with `.attrs['status']` (wide status
    frame) and `.attrs['profile']` (symbol -> profile)."""
    inputs = load_inputs(con, as_of, symbols, with_xbrl=with_xbrl)
    if not inputs:
        return pd.DataFrame()
    rows, wide, status, profile, notes = [], {}, {}, {}, {}
    for sym, inp in inputs.items():
        try:
            ms = compute_all(inp)
        except Exception as e:                       # noqa: BLE001 - one bad name never blocks the slice
            log.warning("metrics failed for %s on %s: %s", sym, as_of, e)
            continue
        rows.extend(ms.rows(as_of, sym, METRICS_VERSION))
        wide[sym] = ms.as_dict()
        status[sym] = {m.name: m.status for m in ms}
        profile[sym] = inp.profile
        notes[sym] = list(inp.notes)
    out = pd.DataFrame.from_dict(wide, orient="index").astype(float).replace([np.inf, -np.inf], np.nan)
    out.attrs["status"] = pd.DataFrame.from_dict(status, orient="index")
    out.attrs["profile"] = pd.Series(profile)
    out.attrs["notes"] = notes
    out.attrs["industry"] = pd.Series({s: i.industry for s, i in inputs.items()})
    out.attrs["feat"] = {s: i.feat for s, i in inputs.items()}
    out.attrs["price"] = pd.Series({s: i.price for s, i in inputs.items()}, dtype=float)
    if store and rows:
        con.execute("DELETE FROM fund_metrics WHERE as_of = ? AND engine_version = ?"
                    + (" AND symbol IN (" + ",".join("?" * len(symbols)) + ")" if symbols else ""),
                    [as_of, METRICS_VERSION, *(symbols or [])])
        upsert(con, "fund_metrics", pd.DataFrame(rows))
    return out


def load_metrics(con: duckdb.DuckDBPyConnection, as_of: date, symbols: Optional[list[str]] = None,
                 engine_version: str = METRICS_VERSION) -> pd.DataFrame:
    """Wide frame from the stored fund_metrics slice (same shape as build_metrics, without feat attrs)."""
    sql = "SELECT symbol, metric, value, status FROM fund_metrics WHERE as_of = ? AND engine_version = ?"
    params: list = [as_of, engine_version]
    if symbols:
        sql += " AND symbol IN (" + ",".join("?" * len(symbols)) + ")"
        params += list(symbols)
    df = con.execute(sql, params).df()
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot_table(index="symbol", columns="metric", values="value", aggfunc="first")
    wide = wide.astype(float).replace([np.inf, -np.inf], np.nan)
    st = df.pivot_table(index="symbol", columns="metric", values="status", aggfunc="first")
    # UNKNOWN/NA rows carry NULL values already; keep the status frame for the engine
    wide.attrs["status"] = st
    return wide
