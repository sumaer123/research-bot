"""Pillar 4 — Growth & Reinvestment Runway: non-financial growth metrics, earnings velocity, and sustainability.

Computes from point-in-time Inputs: reinvestment rate, incremental ROIC, fundamental growth,
sales/PAT/EPS CAGRs, growth consistency, and for banks: book value and PPOP growth.

Rules:
- capex = −cash_from_investing_activity clipped ≥ 0 (note 'capex_from_cfi' when using this proxy)
- ΔWC = Δ(other_assets − other_liabilities)
- NOPAT = (operating_profit − depreciation) × (1 − tax_rate)
- IC = equity_capital + reserves + borrowings − investments
- Reinvestment rate clipped to [−0.10, 0.30]; UNKNOWN if ΣNOPAT ≤ 0
- Incremental ROIC: NA (note 'roiic_na_shrinking_ic') when ΔIC ≤ 0
- Fundamental growth = reinvestment × incremental ROIC; clipped to [−0.10, 0.30]
- CAGRs use geometric mean; UNKNOWN when either endpoint ≤ 0
- Growth consistency = share of (FY-over-FY pairs in last ≤5 FYs with sales > 0 AND PAT > 0)
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .base import Inputs, MetricSet, ok, unknown, na


def _cagr_series(series: pd.Series, n_years: int) -> Optional[float]:
    """CAGR from the start of series to end, spanning n_years.
    Returns UNKNOWN (None) if either endpoint <= 0 or insufficient data."""
    if len(series) < max(2, n_years):
        return None
    start_val = series.iloc[0]
    end_val = series.iloc[-1]
    if start_val is None or end_val is None or pd.isna(start_val) or pd.isna(end_val):
        return None
    start_val, end_val = float(start_val), float(end_val)
    if start_val <= 0 or end_val <= 0:
        return None
    years = (pd.Timestamp(series.index[-1]) - pd.Timestamp(series.index[0])).days / 365.25
    if years <= 0:
        return None
    return float((end_val / start_val) ** (1 / years) - 1)


def compute(inp: Inputs, ctx: Optional[dict] = None) -> MetricSet:
    """Compute growth pillar metrics from point-in-time Inputs.

    ctx is unused by growth (but valuation will call growth first and pass ctx).
    Non-financial formulas return NA() for banks and NBFC_FIN.
    """
    ctx = ctx or {}
    ms = MetricSet()

    # --- Non-financial metrics (NA for BANK/NBFC_FIN) ---

    if not inp.is_financial:
        # Reinvestment rate over the last ≤5 years
        reinv_rate = _reinvestment_rate_5y(inp)
        ms.add(ok("reinvestment_rate_5y", reinv_rate, unit="ratio",
                  inputs_as_of=inp.latest_period(),
                  note="capex_from_cfi" if reinv_rate is not None else ""))

        # Incremental ROIC over the last ≤5 years
        inc_roic, roic_note = _incremental_roic_5y(inp)
        if roic_note:
            ms.add(unknown("incremental_roic_5y", note=roic_note, unit="ratio"))
        else:
            ms.add(ok("incremental_roic_5y", inc_roic, unit="ratio",
                      inputs_as_of=inp.latest_period()))

        # Fundamental growth = reinvestment × incremental ROIC
        if reinv_rate is not None and inc_roic is not None:
            fund_growth = float(reinv_rate * inc_roic)
            fund_growth = max(-0.10, min(0.30, fund_growth))  # Clip to [-10%, +30%]
            ms.add(ok("fundamental_growth", fund_growth, unit="ratio",
                      inputs_as_of=inp.latest_period()))
        else:
            ms.add(unknown("fundamental_growth", unit="ratio",
                          note="missing reinvestment_rate or incremental_roic"))
    else:
        ms.add(na("reinvestment_rate_5y"))
        ms.add(na("incremental_roic_5y"))
        ms.add(na("fundamental_growth"))

    # --- CAGRs (apply to all profiles) ---

    # Sales CAGR 3y
    sales_series_3y = inp.a_series("sales").fillna(inp.a_series("revenue"))
    if len(sales_series_3y) > 0:
        sales_cagr_3y = _cagr_series(sales_series_3y, 3)
        ms.add(ok("sales_cagr_3y", sales_cagr_3y, unit="ratio",
                  inputs_as_of=inp.latest_period()))
    else:
        ms.add(unknown("sales_cagr_3y", unit="ratio", note="no sales history"))

    # Sales CAGR 5y
    if len(sales_series_3y) > 0:
        sales_cagr_5y = _cagr_series(sales_series_3y, 5)
        ms.add(ok("sales_cagr_5y", sales_cagr_5y, unit="ratio",
                  inputs_as_of=inp.latest_period()))
    else:
        ms.add(unknown("sales_cagr_5y", unit="ratio", note="no sales history"))

    # PAT CAGR 5y
    pat_series = inp.a_series("net_profit")
    if len(pat_series) > 0:
        pat_cagr_5y = _cagr_series(pat_series, 5)
        ms.add(ok("pat_cagr_5y", pat_cagr_5y, unit="ratio",
                  inputs_as_of=inp.latest_period()))
    else:
        ms.add(unknown("pat_cagr_5y", unit="ratio", note="no net_profit history"))

    # EPS CAGR 5y
    eps_series = inp.a_series("eps_in_rs")
    if len(eps_series) > 0:
        eps_cagr_5y = _cagr_series(eps_series, 5)
        ms.add(ok("eps_cagr_5y", eps_cagr_5y, unit="ratio",
                  inputs_as_of=inp.latest_period()))
    else:
        ms.add(unknown("eps_cagr_5y", unit="ratio", note="no eps_in_rs history"))

    # Growth consistency: share of FY-over-FY pairs with sales > 0 AND PAT > 0
    gc = _growth_consistency_5y(inp)
    ms.add(ok("growth_consistency_5y", gc, unit="ratio",
              inputs_as_of=inp.latest_period()))

    # --- TTM YoY metrics ---

    sales_ttm = inp.ttm_sales()
    # For TTM prev: use annual fallback if quarterly not sufficient
    if inp.n_years() >= 2:
        sales_prev = inp.sales(-2)  # Annual fallback
        if sales_ttm is not None and sales_prev is not None and sales_prev != 0:
            sales_yoy_ttm = sales_ttm / sales_prev - 1
        else:
            sales_yoy_ttm = None
    else:
        sales_yoy_ttm = None
    ms.add(ok("sales_yoy_ttm", sales_yoy_ttm, unit="ratio",
              inputs_as_of=inp.latest_period()))

    pat_ttm = inp.ttm("net_profit")
    # For TTM prev, use annual fallback
    if inp.n_years() >= 2:
        pat_prev = inp.a("net_profit", -2)
        if pat_ttm is not None and pat_prev is not None and pat_prev != 0:
            pat_yoy_ttm = (pat_ttm - pat_prev) / abs(pat_prev)
        else:
            pat_yoy_ttm = None
    else:
        pat_yoy_ttm = None
    ms.add(ok("pat_yoy_ttm", pat_yoy_ttm, unit="ratio",
              inputs_as_of=inp.latest_period()))

    # --- Financial profile metrics ---

    if inp.is_financial:
        # Book value per share CAGR 5y
        if "equity_capital" in inp.annual.columns and "face_value" in [inp.face_value]:
            eq_series = inp.a_series("equity_capital")
            if inp.face_value and inp.face_value > 0 and len(eq_series) > 0:
                bvps_series = eq_series / inp.face_value
                bvps_cagr_5y = _cagr_series(bvps_series, 5)
                ms.add(ok("bvps_cagr_5y", bvps_cagr_5y, unit="ratio",
                          inputs_as_of=inp.latest_period()))
            else:
                ms.add(unknown("bvps_cagr_5y", unit="ratio", note="missing face_value"))
        else:
            ms.add(unknown("bvps_cagr_5y", unit="ratio", note="no equity_capital history"))

        # Pre-provision operating profit (PPOP) growth 3y
        # PPOP proxy = financing_profit + other_income
        ppop_series = inp.a_series("financing_profit").fillna(0) + inp.a_series("other_income").fillna(0)
        # Remove NaN rows
        ppop_series = ppop_series[(inp.a_series("financing_profit").notna()) |
                                  (inp.a_series("other_income").notna())]
        if len(ppop_series) > 0:
            ppop_growth_3y = _cagr_series(ppop_series, 3)
            ms.add(ok("ppop_growth_3y", ppop_growth_3y, unit="ratio",
                      inputs_as_of=inp.latest_period()))
        else:
            ms.add(unknown("ppop_growth_3y", unit="ratio", note="no financing_profit/other_income history"))
    else:
        ms.add(na("bvps_cagr_5y"))
        ms.add(na("ppop_growth_3y"))

    return ms


def _reinvestment_rate_5y(inp: Inputs) -> Optional[float]:
    """Reinvestment rate = Σ(capex − depreciation + ΔWC) / Σ NOPAT over ≤5 years.

    capex = −cash_from_investing_activity clipped ≥ 0 (note: this is a proxy, r1 method)
    ΔWC = change in (other_assets − other_liabilities)
    NOPAT = (operating_profit − depreciation) × (1 − tax_rate)
    """
    if inp.n_years() < 2:
        return None
    # last <= 5 fiscal years plus the year before them (for the working-capital delta)
    annual = inp.annual.iloc[-6:]
    col = lambda name: annual[name].astype(float) if name in annual.columns else pd.Series(np.nan, index=annual.index)  # noqa: E731
    cfi, dep, oa, ol = col("cash_from_investing_activity"), col("depreciation"), col("other_assets"), col("other_liabilities")
    op = col("operating_profit")
    if op.isna().all():
        op = col("financing_profit")
    years = annual.index[1:] if len(annual) > 5 else annual.index[1:]      # rows 1.. of the 6-row window
    capex_total = depreciation_total = dwc_total = nopat_total = 0.0
    n_nopat = 0
    for i, d in enumerate(annual.index):
        if i == 0 and len(annual) == 6:
            continue                                     # base year for the delta only
        if pd.notna(cfi.get(d)):
            capex_total += max(0.0, -float(cfi[d]))
        if pd.notna(dep.get(d)):
            depreciation_total += float(dep[d])
        prev = annual.index[i - 1] if i > 0 else None
        if prev is not None and all(pd.notna(x) for x in (oa.get(d), ol.get(d), oa.get(prev), ol.get(prev))):
            dwc_total += (float(oa[d]) - float(ol[d])) - (float(oa[prev]) - float(ol[prev]))
        if pd.notna(op.get(d)) and pd.notna(dep.get(d)):
            nopat_total += (float(op[d]) - float(dep[d])) * (1 - inp.tax_rate)
            n_nopat += 1
    if nopat_total <= 0 or n_nopat == 0:
        return None
    return float((capex_total - depreciation_total + dwc_total) / nopat_total)


def _incremental_roic_5y(inp: Inputs) -> tuple[Optional[float], str]:
    """Incremental ROIC = (NOPAT_t − NOPAT_t−5) / (IC_t − IC_t−5)
    IC = equity_capital + reserves + borrowings − investments

    Returns (value, note) where note is empty on success, or the NA reason (e.g. 'roiic_na_shrinking_ic').
    Uses ≥3 years apart if 5 years unavailable.
    """
    n = inp.n_years()
    if n < 2:
        return None, ""

    # Determine the gap: prefer 5 years, fall back to 3+ years
    gap = min(5, n - 1)
    if gap < 3:
        return None, ""

    # Get NOPAT at start and end
    op_start = inp.a("operating_profit", -(n))
    dep_start = inp.a("depreciation", -(n))
    op_end = inp.a("operating_profit", -1)
    dep_end = inp.a("depreciation", -1)

    if op_start is None or dep_start is None or op_end is None or dep_end is None:
        return None, ""

    nopat_start = (op_start - dep_start) * (1 - inp.tax_rate)
    nopat_end = (op_end - dep_end) * (1 - inp.tax_rate)
    nopat_change = nopat_end - nopat_start

    # Calculate IC at start and end
    eq_start = inp.a("equity_capital", -(n))
    res_start = inp.a("reserves", -(n))
    bor_start = inp.borrowings(-(n))
    inv_start = inp.a("investments", -(n))

    eq_end = inp.a("equity_capital", -1)
    res_end = inp.a("reserves", -1)
    bor_end = inp.borrowings(-1)
    inv_end = inp.a("investments", -1)

    if any(x is None for x in [eq_start, res_start, bor_start, inv_start, eq_end, res_end, bor_end, inv_end]):
        return None, ""

    ic_start = eq_start + res_start + bor_start - inv_start
    ic_end = eq_end + res_end + bor_end - inv_end
    ic_change = ic_end - ic_start

    if ic_change <= 0:
        return None, "roiic_na_shrinking_ic"

    return float(nopat_change / ic_change), ""


def _growth_consistency_5y(inp: Inputs) -> Optional[float]:
    """Share of (FY-over-FY pairs in the last ≤5 FYs) with sales growth > 0 AND PAT growth > 0."""
    if inp.n_years() < 2:
        return None

    annual = inp.annual.iloc[-5:]
    sales_col = "sales" if "sales" in annual.columns else "revenue"

    if sales_col not in annual.columns or "net_profit" not in annual.columns:
        return None

    sales = annual[sales_col].astype(float)
    pat = annual["net_profit"].astype(float)

    if len(sales) < 2 or len(pat) < 2:
        return None

    good_years = 0
    total_pairs = 0

    for i in range(1, len(sales)):
        if pd.notna(sales.iloc[i]) and pd.notna(sales.iloc[i-1]) and \
           pd.notna(pat.iloc[i]) and pd.notna(pat.iloc[i-1]):
            total_pairs += 1
            if sales.iloc[i] > 0 and sales.iloc[i-1] > 0 and \
               pat.iloc[i] > 0 and pat.iloc[i-1] > 0 and \
               sales.iloc[i] > sales.iloc[i-1] and pat.iloc[i] > pat.iloc[i-1]:
                good_years += 1

    if total_pairs == 0:
        return None

    return float(good_years / total_pairs)
