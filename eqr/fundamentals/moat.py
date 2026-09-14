"""Pillar 1 — Economic Moat & Business Quality.

Metrics: ROIC, WACC, spread, ROCE, operating margins, pricing power, moat persistence.
Non-financial profiles emit ROIC-based metrics; financial profiles emit ROA/ROE-based metrics.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .base import Inputs, MetricSet, ok, unknown, na, OK


def compute(inp: Inputs, ctx: dict | None = None) -> MetricSet:
    """Compute moat metrics for non-financial and financial profiles.

    Returns:
        MetricSet with all P1_MOAT component names (OK, UNKNOWN, or NA depending on profile and data).
    """
    result = MetricSet()

    if inp.is_financial:
        _add_financial_moat(inp, result)
    else:
        _add_nonfin_moat(inp, result)

    return result


# ---------- Non-financial profile metrics


def _add_nonfin_moat(inp: Inputs, result: MetricSet) -> None:
    """Add moat metrics for GENERAL, IT_SERVICES, PHARMA, CYCLICAL profiles."""

    # --- ROIC, WACC, spread (the foundation)
    wacc_val = _wacc(inp)
    roic_ttm_val = _roic_ttm(inp)

    result.add(ok("roic_ttm", roic_ttm_val, unit="ratio",
                  note="informational" if roic_ttm_val is not None else ""))
    result.add(ok("wacc", wacc_val, unit="ratio",
                  note="informational" if wacc_val is not None else ""))

    # spread_ttm = roic_ttm - wacc
    spread_ttm_val = None
    if roic_ttm_val is not None and wacc_val is not None:
        spread_ttm_val = roic_ttm_val - wacc_val
    result.add(ok("spread_ttm", spread_ttm_val, unit="ratio"))

    # --- ROCE-based metrics
    roce_10y = _roce_median_10y(inp)
    roce_10y_min = _roce_min_10y(inp)
    result.add(ok("roce_median_10y", roce_10y, unit="ratio"))
    result.add(ok("roce_min_10y", roce_10y_min, unit="ratio"))

    # --- Operating margin metrics
    opm_8y_median, opm_8y_cv = _opm_median_8y(inp)
    result.add(ok("opm_median_8y", opm_8y_median, unit="ratio"))
    result.add(ok("opm_cv_8y", opm_8y_cv, unit="ratio"))

    # --- Gross margin metrics (r2 XBRL-only)
    gm_5y_median, gm_5y_cv = _gross_margin_median_5y(inp)
    result.add(ok("gross_margin_median_5y", gm_5y_median, unit="ratio",
                  note="xbrl_required" if gm_5y_median is None else ""))
    result.add(ok("gm_stability_5y", gm_5y_cv, unit="ratio",
                  note="xbrl_required" if gm_5y_cv is None else ""))

    # --- Pricing power proxy: OPM change in years with lowest sales growth
    pp_proxy = _pricing_power_proxy(inp)
    result.add(ok("pricing_power_proxy", pp_proxy, unit="ratio"))

    # --- Moat persistence: share of years with ROCE > WACC
    moat_persist = _moat_persistence(inp, wacc_val)
    result.add(ok("moat_persistence", moat_persist, unit="ratio"))

    # --- Spread trend over 5 years (slope in pp/yr)
    spread_trend = _spread_trend_5y(inp)
    result.add(ok("spread_trend_5y", spread_trend, unit="ratio"))

    # --- Spread median 5y
    spread_5y_median = _spread_median_5y(inp)
    result.add(ok("spread_median_5y", spread_5y_median, unit="ratio"))

    # --- Financial profile metrics as NA
    result.add(na("roa_ttm"))
    result.add(na("roe_coe_spread"))
    result.add(na("nim_pct"))
    result.add(na("cost_to_income"))
    result.add(na("roe_median_5y"))

    # --- LLM-only component (r3)
    result.add(na("moat_grade_llm"))


def _add_financial_moat(inp: Inputs, result: MetricSet) -> None:
    """Add moat metrics for BANK and NBFC_FIN profiles."""

    # --- ROA_TTM: PAT_ttm / avg total_assets
    roa_val = _roa_ttm(inp)
    result.add(ok("roa_ttm", roa_val, unit="ratio"))

    # --- ROE - CoE spread
    roe_coe = _roe_coe_spread(inp)
    result.add(ok("roe_coe_spread", roe_coe, unit="ratio"))

    # --- NIM (Net Interest Margin)
    nim = _nim_pct(inp)
    result.add(ok("nim_pct", nim, unit="ratio"))

    # --- Cost-to-income ratio
    c2i = _cost_to_income(inp)
    result.add(ok("cost_to_income", c2i, unit="ratio"))

    # --- ROE median over 5y
    roe_5y = _roe_median_5y(inp)
    result.add(ok("roe_median_5y", roe_5y, unit="ratio"))

    # --- Non-financial metrics as NA
    result.add(na("roic_ttm"))
    result.add(na("wacc"))
    result.add(na("spread_ttm"))
    result.add(na("spread_median_5y"))
    result.add(na("spread_trend_5y"))
    result.add(na("roce_median_10y"))
    result.add(na("roce_min_10y"))
    result.add(na("opm_median_8y"))
    result.add(na("opm_cv_8y"))
    result.add(na("gross_margin_median_5y"))
    result.add(na("gm_stability_5y"))
    result.add(na("pricing_power_proxy"))
    result.add(na("moat_persistence"))

    # --- LLM-only component (r3)
    result.add(na("moat_grade_llm"))


# ---------- ROIC and WACC calculations


def _roic_ttm(inp: Inputs) -> Optional[float]:
    """ROIC = NOPAT_ttm / avg(IC_t, IC_t-1).

    NOPAT = EBIT_op × (1 − tax_rate)
    EBIT_op = operating_profit − depreciation (other_income EXCLUDED)
    IC = equity_capital + reserves + borrowings − non-operating assets
    non-operating assets = cash + investments (XBRL r2) or investments alone (r1)
    """
    nopat = _nopat_ttm(inp)
    if nopat is None:
        return None

    ic_current = _invested_capital(inp, i=-1)
    ic_prior = _invested_capital(inp, i=-2)

    if ic_current is None or (ic_current <= 0 and ic_prior is None):
        return None

    avg_ic = ic_current
    if ic_prior is not None and ic_prior > 0:
        avg_ic = (ic_current + ic_prior) / 2.0
    elif ic_prior is None:
        avg_ic = ic_current

    if avg_ic <= 0:
        return None

    return nopat / avg_ic


def _nopat_ttm(inp: Inputs) -> Optional[float]:
    """NOPAT = EBIT_op × (1 − tax_rate).

    EBIT_op = operating_profit − depreciation (other_income excluded)
    """
    op_ttm = inp.ttm_op()
    dep_ttm = inp.ttm("depreciation")

    if op_ttm is None or dep_ttm is None:
        return None

    ebit_op = op_ttm - dep_ttm
    if ebit_op is None:
        return None

    nopat = ebit_op * (1.0 - inp.tax_rate)
    return nopat if math.isfinite(nopat) else None


def _invested_capital(inp: Inputs, i: int = -1) -> Optional[float]:
    """IC = equity_capital + reserves + borrowings − non-operating assets.

    Non-operating assets: cash + investments (XBRL r2) or investments alone (r1).
    """
    eq = inp.a("equity_capital", i)
    res = inp.a("reserves", i)
    bor = inp.borrowings(i)

    if eq is None or res is None or bor is None:
        return None

    # non-operating assets: prefer XBRL cash+investments, else investments proxy
    nonop = 0.0
    if inp.xbrl and "cash" in inp.xbrl and "investments" in inp.xbrl:
        nonop = (inp.xbrl.get("cash") or 0.0) + (inp.xbrl.get("investments") or 0.0)
    else:
        inv = inp.a("investments", i)
        if inv is not None:
            nonop = inv

    ic = eq + res + bor - nonop
    return ic


def _wacc(inp: Inputs) -> Optional[float]:
    """WACC = E/(D+E)·Ke + D/(D+E)·Kd·(1−t).

    Ke = rf + β·ERP; β = 0.67·clip(beta_250, 0.6, 1.6) + 0.33·1.0
    Kd = interest / avg borrowings, clipped [rf, rf+8%]
    E = mcap (feat['mcap_cr'] or price×shares from equity_capital/face_value)
    D = borrowings
    Floor: wacc ≥ g_terminal + 3%
    """
    # Get market cap
    mcap_cr = inp.feat.get("mcap_cr")
    if mcap_cr is None or not math.isfinite(float(mcap_cr)):
        # Try to compute from price and equity_capital / face_value
        if inp.price is not None and inp.face_value is not None and inp.face_value > 0:
            eq = inp.a("equity_capital", -1)
            if eq is not None and eq > 0:
                shares = eq / inp.face_value
                mcap_cr = (inp.price * shares) / 1e7  # convert to crore
            else:
                return None
        else:
            return None

    e_val = mcap_cr if mcap_cr > 0 else None
    if e_val is None:
        return None

    # Get borrowings and debt
    d_val = inp.borrowings(-1)
    if d_val is None or d_val <= 0:
        # If no borrowings, WACC ≈ Ke
        ke = _cost_of_equity(inp)
        if ke is None:
            return None
        wacc = ke
    else:
        # Cost of equity
        ke = _cost_of_equity(inp)
        if ke is None:
            return None

        # Cost of debt
        kd = _cost_of_debt(inp)
        if kd is None:
            kd = inp.rf_pct / 100.0

        # WACC = E/(D+E)·Ke + D/(D+E)·Kd·(1−t)
        e_weight = e_val / (d_val + e_val)
        d_weight = d_val / (d_val + e_val)
        wacc = e_weight * ke + d_weight * kd * (1.0 - inp.tax_rate)

    # Floor: wacc ≥ g_terminal + 3%
    floor = inp.g_terminal + 0.03
    if wacc < floor:
        wacc = floor
        inp.notes.append("wacc_floored")

    return wacc if math.isfinite(wacc) else None


def _cost_of_equity(inp: Inputs) -> Optional[float]:
    """Ke = rf + β·ERP.

    β = 0.67·clip(beta_250, 0.6, 1.6) + 0.33·1.0 (Blume shrinkage; default 1.0 if missing)
    """
    rf = inp.rf_pct / 100.0
    erp = inp.erp_pct / 100.0

    beta = inp.feat.get("beta_250")
    if beta is None or not math.isfinite(float(beta)):
        beta_adj = 1.0
        inp.notes.append("beta_missing")
    else:
        beta_float = float(beta)
        beta_clipped = max(0.6, min(1.6, beta_float))
        beta_adj = 0.67 * beta_clipped + 0.33 * 1.0

    ke = rf + beta_adj * erp
    return ke if math.isfinite(ke) else None


def _cost_of_debt(inp: Inputs) -> Optional[float]:
    """Kd = interest / avg borrowings, clipped [rf, rf+8%].

    If borrowings ≤ 0, return None (weight D = 0 in WACC).
    """
    interest_ttm = inp.ttm("interest")
    if interest_ttm is None or interest_ttm <= 0:
        return None

    bor_current = inp.borrowings(-1)
    bor_prior = inp.borrowings(-2)

    if bor_current is None or bor_current <= 0:
        if bor_prior is None or bor_prior <= 0:
            return None
        avg_bor = bor_prior
    else:
        if bor_prior is None or bor_prior <= 0:
            avg_bor = bor_current
        else:
            avg_bor = (bor_current + bor_prior) / 2.0

    if avg_bor <= 0:
        return None

    kd = interest_ttm / avg_bor
    rf = inp.rf_pct / 100.0
    kd = max(rf, min(rf + 0.08, kd))
    return kd


# ---------- Other ROIC-based metrics


def _roce_median_10y(inp: Inputs) -> Optional[float]:
    """ROCE median over last 10 years from screener roce_pct (divide by 100)."""
    series = inp.a_series("roce_pct")
    if series.empty:
        return None
    # Take last 10 values
    recent = series.tail(10)
    if recent.empty or recent.notna().sum() == 0:
        return None
    # Convert from percent to fraction
    vals = recent.dropna() / 100.0
    if len(vals) == 0:
        return None
    return float(vals.median())


def _roce_min_10y(inp: Inputs) -> Optional[float]:
    """ROCE minimum over last 10 years from screener roce_pct (divide by 100)."""
    series = inp.a_series("roce_pct")
    if series.empty:
        return None
    recent = series.tail(10)
    vals = recent.dropna() / 100.0
    if len(vals) == 0:
        return None
    return float(vals.min())


def _opm_median_8y(inp: Inputs) -> tuple[Optional[float], Optional[float]]:
    """OPM median and CV over last 8 years.

    OPM from opm_pct in screener (already a percent) or computed from (operating_profit / sales).
    Returns: (median_opm, cv_opm) both as fractions (e.g., 0.15 = 15%).
    """
    series = inp.a_series("opm_pct")
    if series.empty:
        return None, None

    recent = series.tail(8)
    vals = recent.dropna() / 100.0  # convert from percent to fraction
    if len(vals) < 2:
        return None, None

    median = float(vals.median())
    mean = float(vals.mean())
    if mean == 0 or mean < 0:
        return median, None
    cv = float(vals.std() / mean)  # coefficient of variation
    return median, cv


def _gross_margin_median_5y(inp: Inputs) -> tuple[Optional[float], Optional[float]]:
    """Gross margin median and stability (CV) over last 5 years.

    GM = (revenue - COGS) / revenue
    COGS from XBRL: cost_of_materials + purchases + Δinventories
    Returns (r2): (gm_median, gm_cv); (r1): (None, None) with note 'xbrl_required'
    """
    if not inp.xbrl or "revenue" not in inp.xbrl or not all(
        k in inp.xbrl for k in ["cost_of_materials", "purchases", "inventory_change"]
    ):
        return None, None

    revenue = inp.xbrl.get("revenue")
    cogs = (inp.xbrl.get("cost_of_materials") or 0.0) + (inp.xbrl.get("purchases") or 0.0) + (inp.xbrl.get("inventory_change") or 0.0)

    if revenue is None or revenue <= 0:
        return None, None

    gm = (revenue - cogs) / revenue
    if gm is None or not math.isfinite(gm):
        return None, None

    # For now, return a single value (we'd need historical XBRL for full implementation)
    # Placeholder: return the current value with a note that it's not a full 5y median
    return None, None


def _pricing_power_proxy(inp: Inputs) -> Optional[float]:
    """OPM change in the two years with the lowest sales growth.

    Measures ability to maintain margins during downturns.
    """
    sales_series = inp.a_series("sales")
    if sales_series.empty or len(sales_series) < 3:
        return None

    opm_series = inp.a_series("opm_pct")
    if opm_series.empty or len(opm_series) < 3:
        return None

    # Compute YoY sales growth
    sales_yoy = sales_series.pct_change()

    # Find the two years with lowest sales growth (excluding NaN)
    sales_yoy_clean = sales_yoy.dropna()
    if len(sales_yoy_clean) < 2:
        return None

    # Get the indices of the two lowest growth years
    lowest_idx = sales_yoy_clean.nsmallest(2).index

    # Get OPM values for those years (convert from percent to fraction)
    opm_vals = opm_series.loc[lowest_idx] / 100.0
    if len(opm_vals) != 2 or opm_vals.isna().any():
        return None

    # OPM change (later - earlier)
    opm_change = opm_vals.iloc[-1] - opm_vals.iloc[0]
    return opm_change


def _moat_persistence(inp: Inputs, wacc_val: Optional[float]) -> Optional[float]:
    """Share of last ≤10 years with ROCE > WACC.

    Measures persistence of value creation.
    """
    if wacc_val is None or not math.isfinite(wacc_val):
        return None

    roce_series = inp.a_series("roce_pct")
    if roce_series.empty:
        return None

    recent = roce_series.tail(10)
    roce_vals = recent.dropna() / 100.0

    if len(roce_vals) == 0:
        return None

    # Count how many years ROCE > WACC
    above_wacc = (roce_vals > wacc_val).sum()
    persistence = float(above_wacc) / float(len(roce_vals))
    return persistence


def _spread_trend_5y(inp: Inputs) -> Optional[float]:
    """Slope of yearly (ROIC - WACC) over last 5 years in pp/yr.

    Linear regression: years as x, spread as y; return slope in fractions per year.
    """
    # Need multiple years to compute trend
    if inp.n_years() < 3:
        return None

    # For each year, compute ROIC - WACC
    wacc_val = _wacc(inp)  # Current WACC (used for all years per plan note 'rf_undated')
    if wacc_val is None:
        return None

    spreads = []
    years_idx = []

    for i in range(-min(5, inp.n_years()), 0):
        roic_i = _roic_for_year(inp, i)
        if roic_i is not None:
            spread_i = roic_i - wacc_val
            spreads.append(spread_i)
            years_idx.append(float(i))

    if len(spreads) < 2:
        return None

    # Simple linear regression: slope = Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)
    years_arr = np.array(years_idx)
    spreads_arr = np.array(spreads)

    mean_x = years_arr.mean()
    mean_y = spreads_arr.mean()

    cov = np.sum((years_arr - mean_x) * (spreads_arr - mean_y))
    var_x = np.sum((years_arr - mean_x) ** 2)

    if var_x == 0:
        return None

    slope = cov / var_x
    return slope if math.isfinite(slope) else None


def _roic_for_year(inp: Inputs, i: int) -> Optional[float]:
    """Compute ROIC for year at index i using balance sheet at year i and i-1."""
    nopat_i = _nopat_for_year(inp, i)
    if nopat_i is None:
        return None

    ic_i = _invested_capital(inp, i)
    ic_i_minus_1 = _invested_capital(inp, i - 1)

    if ic_i is None:
        return None

    if ic_i_minus_1 is None or ic_i_minus_1 <= 0:
        avg_ic = ic_i
    else:
        avg_ic = (ic_i + ic_i_minus_1) / 2.0

    if avg_ic <= 0:
        return None

    return nopat_i / avg_ic


def _nopat_for_year(inp: Inputs, i: int) -> Optional[float]:
    """NOPAT for year at index i."""
    op_i = inp.a("operating_profit", i)
    dep_i = inp.a("depreciation", i)

    if op_i is None or dep_i is None:
        return None

    ebit_op_i = op_i - dep_i
    nopat_i = ebit_op_i * (1.0 - inp.tax_rate)
    return nopat_i


def _spread_median_5y(inp: Inputs) -> Optional[float]:
    """Median of yearly (ROIC - WACC) over last 5 years.

    Uses current WACC for all years (per plan note 'rf_undated').
    """
    if inp.n_years() < 2:
        return None

    wacc_val = _wacc(inp)
    if wacc_val is None:
        return None

    spreads = []
    for i in range(-min(5, inp.n_years()), 0):
        roic_i = _roic_for_year(inp, i)
        if roic_i is not None:
            spread_i = roic_i - wacc_val
            spreads.append(spread_i)

    if len(spreads) == 0:
        return None

    return float(np.median(spreads))


# ---------- Financial profile metrics


def _roa_ttm(inp: Inputs) -> Optional[float]:
    """ROA_ttm = PAT_ttm / avg(total_assets)."""
    pat_ttm = inp.ttm("net_profit")
    if pat_ttm is None:
        return None

    ta_current = inp.a("total_assets", -1)
    ta_prior = inp.a("total_assets", -2)

    if ta_current is None or (ta_current <= 0 and ta_prior is None):
        return None

    avg_ta = ta_current if ta_prior is None or ta_prior <= 0 else (ta_current + ta_prior) / 2.0
    if avg_ta <= 0:
        return None

    roa = pat_ttm / avg_ta
    return roa


def _roe_coe_spread(inp: Inputs) -> Optional[float]:
    """ROE_ttm - CoE.

    ROE = PAT_ttm / avg(BVE)
    BVE = equity_capital + reserves
    """
    pat_ttm = inp.ttm("net_profit")
    if pat_ttm is None:
        return None

    bve_current = inp.bve(-1)
    bve_prior = inp.bve(-2)

    if bve_current is None or (bve_current <= 0 and bve_prior is None):
        return None

    avg_bve = bve_current if bve_prior is None or bve_prior <= 0 else (bve_current + bve_prior) / 2.0
    if avg_bve <= 0:
        return None

    roe = pat_ttm / avg_bve

    coe = _cost_of_equity(inp)
    if coe is None:
        return None

    spread = roe - coe
    return spread


def _nim_pct(inp: Inputs) -> Optional[float]:
    """Net interest margin proxy = (interest earned - interest expense) / avg total assets.

    Screener's `financing_margin_pct` is financing profit / revenue (net of opex) and goes
    deeply negative for consolidated banks, so it is NOT a NIM; the NII / assets proxy is.
    """
    rev, intr = inp.sales(-1), inp.a("interest", -1)
    ta0, ta1 = inp.a("total_assets", -1), inp.a("total_assets", -2)
    if rev is None or intr is None or ta0 is None or ta0 <= 0:
        return None
    avg_ta = (ta0 + ta1) / 2 if ta1 is not None and ta1 > 0 else ta0
    return (rev - intr) / avg_ta


def _cost_to_income(inp: Inputs) -> Optional[float]:
    """Cost-to-income = operating expenses / (net interest income + other income).

    Screener's bank P&L: financing_profit = revenue - interest - expenses, so `expenses`
    already excludes interest (it is opex + provisions). Denominator <= 0 -> UNKNOWN.
    """
    exp = inp.a("expenses", -1)
    rev, intr = inp.sales(-1), inp.a("interest", -1)
    other_inc = inp.a("other_income", -1) or 0.0
    if exp is None or rev is None or intr is None:
        return None
    denominator = (rev - intr) + other_inc
    if denominator <= 0:
        return None
    return exp / denominator


def _roe_median_5y(inp: Inputs) -> Optional[float]:
    """ROE median over last 5 years.

    From screener roe_pct (divide by 100).
    """
    series = inp.a_series("roe_pct")
    if series.empty:
        return None

    recent = series.tail(5)
    vals = recent.dropna() / 100.0
    if len(vals) == 0:
        return None

    return float(vals.median())
