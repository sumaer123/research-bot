"""Pillar 2 — Balance Sheet Fortification & Solvency.

Metrics: leverage, interest coverage, working capital, asset quality (for banks), capital ratios.
Non-financial profiles emit debt-based metrics; financial profiles emit capital/asset-quality metrics.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .base import Inputs, MetricSet, ok, unknown, na, OK
from .moat import _invested_capital


def compute(inp: Inputs, ctx: dict | None = None) -> MetricSet:
    """Compute solvency metrics for non-financial and financial profiles.

    Returns:
        MetricSet with all P2_BALANCE component names (OK, UNKNOWN, or NA depending on profile and data).
    """
    result = MetricSet()

    if inp.is_financial:
        _add_financial_solvency(inp, result)
    else:
        _add_nonfin_solvency(inp, result)

    return result


# ---------- Non-financial profile metrics


def _add_nonfin_solvency(inp: Inputs, result: MetricSet) -> None:
    """Add solvency metrics for GENERAL, IT_SERVICES, PHARMA, CYCLICAL profiles."""

    # --- Net debt metrics
    net_debt_val = _net_debt(inp)
    result.add(ok("net_debt_ebitda", None, unit="ratio",
                  note="net_debt informational") if net_debt_val is not None else unknown("net_debt_ebitda"))

    ebitda_ttm = _ebitda_ttm(inp)
    if net_debt_val is not None and ebitda_ttm is not None and ebitda_ttm > 0:
        net_debt_ebitda = net_debt_val / ebitda_ttm
    else:
        net_debt_ebitda = None
    result.add(ok("net_debt_ebitda", net_debt_ebitda, unit="ratio",
                  note="net_debt_investments_proxy" if net_debt_val is not None and
                       not _has_xbrl_cash(inp) else ""))

    # prior-FY net debt / EBITDA (DEBT_SPIKE input): borrowings - investments over the prior FY's operating profit
    bor_p, inv_p, op_p = inp.borrowings(-2), inp.a("investments", -2), inp.op(-2)
    if bor_p is not None and op_p is not None and op_p > 0:
        nd_p = bor_p - (inv_p or 0.0) if bor_p > 0 else 0.0
        result.add(ok("net_debt_ebitda_prev", nd_p / op_p, unit="ratio", note="prior FY, investments proxy"))
    else:
        result.add(unknown("net_debt_ebitda_prev", "prior FY inputs missing"))
    result.add(ok("net_debt", net_debt_val, unit="crore"))

    # --- Net debt / FCF years
    fcf_median_3y = _fcf_median_3y(inp)
    if net_debt_val is not None and fcf_median_3y is not None:
        if fcf_median_3y > 0:
            net_debt_fcf = net_debt_val / fcf_median_3y
        else:
            # FCF ≤ 0 and net_debt > 0 → net_debt_fcf_years = 10.0 with note
            net_debt_fcf = 10.0 if net_debt_val > 0 else 0.0
            if net_debt_val > 0:
                inp.notes.append("fcf_nonpositive")
    else:
        net_debt_fcf = None
    result.add(ok("net_debt_fcf_years", net_debt_fcf, unit="ratio"))

    # --- Interest coverage
    int_cover_ttm = _interest_coverage_ttm(inp)
    result.add(ok("int_cover_ttm", int_cover_ttm, unit="ratio"))

    # Interest coverage minimum over 5y
    int_cover_min_5y = _interest_coverage_min_5y(inp)
    result.add(ok("int_cover_min_5y", int_cover_min_5y, unit="ratio"))

    # --- Altman Z''
    altman = _altman_zpp(inp)
    result.add(ok("altman_zpp", altman, unit="ratio"))

    # --- Debt/Equity and trend
    debt_equity = _debt_equity(inp)
    result.add(ok("debt_equity", debt_equity, unit="ratio"))

    de_trend_3y = _de_trend_3y(inp)
    result.add(ok("de_trend_3y", de_trend_3y, unit="ratio"))

    # --- Working capital metrics
    wc_days_delta_3y = _wc_days_delta_3y(inp)
    result.add(ok("wc_days_delta_3y", wc_days_delta_3y, unit="ratio"))

    # --- XBRL-only metrics (r2)
    current_ratio = _current_ratio(inp)
    result.add(ok("current_ratio", current_ratio, unit="ratio",
                  note="xbrl_required" if current_ratio is None else ""))

    cash_to_debt = _cash_to_debt(inp)
    result.add(ok("cash_to_debt", cash_to_debt, unit="ratio",
                  note="xbrl_required" if cash_to_debt is None else ""))

    st_debt_share = _st_debt_share(inp)
    result.add(ok("st_debt_share", st_debt_share, unit="ratio",
                  note="xbrl_required" if st_debt_share is None else ""))

    # --- Doc extractor components (r3 only)
    result.add(na("contingent_to_networth"))

    # --- Financial metrics as NA
    result.add(na("cet1_pct"))
    result.add(na("gnpa_pct"))
    result.add(na("nnpa_pct"))
    result.add(na("gnpa_trend_4q"))
    result.add(na("provision_coverage"))
    result.add(na("deposit_vs_advance_growth"))
    result.add(na("fin_leverage"))
    result.add(na("borrowing_cost"))


def _add_financial_solvency(inp: Inputs, result: MetricSet) -> None:
    """Add solvency metrics for BANK and NBFC_FIN profiles."""

    # --- Asset quality and capital (BANK primary)
    gnpa_pct = _gnpa_pct(inp)
    result.add(ok("gnpa_pct", gnpa_pct, unit="ratio"))

    nnpa_pct = _nnpa_pct(inp)
    result.add(ok("nnpa_pct", nnpa_pct, unit="ratio"))

    gnpa_trend_4q = _gnpa_trend_4q(inp)
    result.add(ok("gnpa_trend_4q", gnpa_trend_4q, unit="ratio"))

    # --- Capital ratios (r2 XBRL-only for banks)
    cet1_pct = _cet1_pct(inp)
    result.add(ok("cet1_pct", cet1_pct, unit="ratio",
                  note="xbrl_required" if cet1_pct is None else ""))

    provision_coverage = _provision_coverage(inp)
    result.add(ok("provision_coverage", provision_coverage, unit="ratio",
                  note="xbrl_required" if provision_coverage is None else ""))

    # --- Deposit/advance growth (BANK)
    if inp.is_bank:
        dep_adv_growth = _deposit_vs_advance_growth(inp)
        result.add(ok("deposit_vs_advance_growth", dep_adv_growth, unit="ratio"))
    else:
        result.add(na("deposit_vs_advance_growth"))

    # --- Leverage (NBFC_FIN)
    fin_leverage = _fin_leverage(inp)
    result.add(ok("fin_leverage", fin_leverage, unit="ratio"))

    borrowing_cost = _borrowing_cost(inp)
    result.add(ok("borrowing_cost", borrowing_cost, unit="ratio"))

    # --- Doc extractor components (r3 only)
    result.add(na("contingent_to_networth"))

    # --- Non-financial metrics as NA
    result.add(na("net_debt_ebitda"))
    result.add(na("net_debt_fcf_years"))
    result.add(na("int_cover_ttm"))
    result.add(na("int_cover_min_5y"))
    result.add(na("altman_zpp"))
    result.add(na("current_ratio"))
    result.add(na("cash_to_debt"))
    result.add(na("st_debt_share"))
    result.add(na("wc_days_delta_3y"))
    result.add(na("debt_equity"))
    result.add(na("de_trend_3y"))


# ---------- Non-financial metrics


def _net_debt(inp: Inputs) -> Optional[float]:
    """Net debt (informational) = borrowings - (cash + investments or investments alone).

    Returns in crores.
    """
    bor = inp.borrowings(-1)
    if bor is None or bor <= 0:
        return 0.0

    # Prefer XBRL cash + investments, else investments proxy
    if inp.xbrl and "cash" in inp.xbrl:
        cash = inp.xbrl.get("cash") or 0.0
        inv = inp.xbrl.get("investments") or 0.0
        nonop = cash + inv
    else:
        inv = inp.a("investments", -1)
        nonop = inv if inv is not None else 0.0

    net_debt = bor - nonop
    return net_debt


def _has_xbrl_cash(inp: Inputs) -> bool:
    """Check if XBRL has cash data."""
    return inp.xbrl and "cash" in inp.xbrl


def _ebitda_ttm(inp: Inputs) -> Optional[float]:
    """EBITDA_ttm = operating_profit_ttm."""
    return inp.ttm_op()


def _fcf_median_3y(inp: Inputs) -> Optional[float]:
    """Median free cash flow over last 3 years."""
    series = inp.a_series("free_cash_flow")
    if series.empty:
        return None

    recent = series.tail(3)
    vals = recent.dropna()
    if len(vals) == 0:
        return None

    return float(vals.median())


def _interest_coverage_ttm(inp: Inputs) -> Optional[float]:
    """Interest coverage = EBIT / interest.

    EBIT = operating_profit (with depreciation).
    """
    ebit_ttm = inp.ttm_op()
    int_ttm = inp.ttm("interest")

    if ebit_ttm is None or int_ttm is None or int_ttm <= 0:
        return None

    return ebit_ttm / int_ttm


def _interest_coverage_min_5y(inp: Inputs) -> Optional[float]:
    """Minimum interest coverage over last 5 years."""
    op_series = inp.a_series("operating_profit")
    int_series = inp.a_series("interest")

    if op_series.empty or int_series.empty:
        return None

    # Align both series
    common_idx = op_series.index.intersection(int_series.index)
    if len(common_idx) == 0:
        return None

    op_vals = op_series.loc[common_idx].tail(5)
    int_vals = int_series.loc[common_idx].tail(5)

    # Compute coverage for each year
    ic_vals = []
    for idx in op_vals.index:
        op_val = op_vals[idx]
        int_val = int_vals[idx]
        if pd.notna(op_val) and pd.notna(int_val) and int_val > 0:
            ic_vals.append(op_val / int_val)

    if len(ic_vals) == 0:
        return None

    return float(np.min(ic_vals))


def _altman_zpp(inp: Inputs) -> Optional[float]:
    """Altman Z'' score.

    Z'' = 3.25 + 6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT/TA + 1.05·BVE/TL

    WC from XBRL current_assets - current_liabilities (r2) or screener other_assets - other_liabilities.
    Uses exactly the same formula as features/fundamental.py::_altman.
    """
    ta = inp.a("total_assets", -1)
    oa = inp.a("other_assets", -1)
    ol = inp.a("other_liabilities", -1)
    re = inp.a("reserves", -1)
    op = inp.a("operating_profit", -1)
    dep = inp.a("depreciation", -1)
    oi = inp.a("other_income", -1)
    eq = inp.a("equity_capital", -1)
    bor = inp.borrowings(-1)

    if any(pd.isna(x) for x in (ta, oa, ol, re, op, dep, eq, bor)) or ta is None or ta <= 0:
        return None

    tl = bor + ol
    if tl is None or tl <= 0:
        return None

    # Try XBRL working capital first
    wc = None
    if inp.xbrl and "current_assets" in inp.xbrl and "current_liabilities" in inp.xbrl:
        ca = inp.xbrl.get("current_assets")
        cl = inp.xbrl.get("current_liabilities")
        if ca is not None and cl is not None:
            wc = ca - cl

    # Fallback to screener other_assets - other_liabilities
    if wc is None:
        wc = oa - ol

    if wc is None:
        return None

    # EBIT = operating_profit - depreciation + other_income (per existing _altman)
    ebit = op - dep
    if oi is not None and pd.notna(oi):
        ebit = ebit + oi

    bve = eq + re
    if bve is None or bve <= 0:
        return None

    z_pp = 3.25 + 6.56 * wc / ta + 3.26 * re / ta + 6.72 * ebit / ta + 1.05 * bve / tl
    return z_pp if math.isfinite(z_pp) else None


def _debt_equity(inp: Inputs) -> Optional[float]:
    """Debt/Equity = borrowings / BVE."""
    bor = inp.borrowings(-1)
    bve = inp.bve(-1)

    if bor is None or bve is None or bve <= 0:
        return None

    de = bor / bve
    return de


def _de_trend_3y(inp: Inputs) -> Optional[float]:
    """D/E trend over 3 years: slope in pp/yr (linear regression).

    Sign: negative slope is positive (improving) for solvency.
    """
    de_series = []
    years_idx = []

    for i in range(-min(3, inp.n_years()), 0):
        bor_i = inp.borrowings(i)
        bve_i = inp.bve(i)
        if bor_i is not None and bve_i is not None and bve_i > 0:
            de_i = bor_i / bve_i
            de_series.append(de_i)
            years_idx.append(float(i))

    if len(de_series) < 2:
        return None

    years_arr = np.array(years_idx)
    de_arr = np.array(de_series)

    mean_x = years_arr.mean()
    mean_y = de_arr.mean()

    cov = np.sum((years_arr - mean_x) * (de_arr - mean_y))
    var_x = np.sum((years_arr - mean_x) ** 2)

    if var_x == 0:
        return None

    slope = cov / var_x
    return slope if math.isfinite(slope) else None


def _wc_days_delta_3y(inp: Inputs) -> Optional[float]:
    """WC days change over 3 years.

    From screener working_capital_days.
    """
    wc_days_series = inp.a_series("working_capital_days")
    if wc_days_series.empty:
        return None

    # Get current and 3 years ago
    current = wc_days_series.iloc[-1]
    idx_3y_ago = max(0, len(wc_days_series) - 4)  # 3 years back
    prior = wc_days_series.iloc[idx_3y_ago]

    if pd.isna(current) or pd.isna(prior):
        return None

    delta = current - prior
    return delta


def _current_ratio(inp: Inputs) -> Optional[float]:
    """Current ratio = current_assets / current_liabilities.

    Requires XBRL (r2).
    """
    if not inp.xbrl:
        return None

    ca = inp.xbrl.get("current_assets")
    cl = inp.xbrl.get("current_liabilities")

    if ca is None or cl is None or cl <= 0:
        return None

    return ca / cl


def _cash_to_debt(inp: Inputs) -> Optional[float]:
    """Cash / borrowings.

    Requires XBRL (r2).
    """
    if not inp.xbrl:
        return None

    cash = inp.xbrl.get("cash")
    bor = inp.borrowings(-1)

    if cash is None or bor is None or bor <= 0:
        return None

    ratio = cash / bor
    return ratio


def _st_debt_share(inp: Inputs) -> Optional[float]:
    """ST debt share = borrowings_current / borrowings.

    Requires XBRL (r2).
    """
    if not inp.xbrl:
        return None

    st_bor = inp.xbrl.get("borrowings_current")
    tot_bor = inp.borrowings(-1)

    if st_bor is None or tot_bor is None or tot_bor <= 0:
        return None

    share = st_bor / tot_bor
    return share


# ---------- Financial profile metrics


def _gnpa_pct(inp: Inputs) -> Optional[float]:
    """GNPA % from latest quarterly (screener gross_npa_pct).

    Returns as fraction (e.g., 0.03 for 3%).
    """
    gnpa = inp.q("gross_npa_pct", -1)
    if gnpa is None or not math.isfinite(gnpa):
        return None
    return gnpa / 100.0


def _nnpa_pct(inp: Inputs) -> Optional[float]:
    """NNPA % from latest quarterly (screener net_npa_pct).

    Returns as fraction.
    """
    nnpa = inp.q("net_npa_pct", -1)
    if nnpa is None or not math.isfinite(nnpa):
        return None
    return nnpa / 100.0


def _gnpa_trend_4q(inp: Inputs) -> Optional[float]:
    """GNPA trend: change from 4 quarters ago (in pp).

    Returns change in percentage points (e.g., +0.01 for +1pp).
    """
    if inp.quarterly.empty:
        return None

    current = inp.q("gross_npa_pct", -1)
    prior_4q = inp.q("gross_npa_pct", -5)

    if current is None or prior_4q is None:
        return None

    # Both are in percentage points already, so difference is in pp
    trend = (current - prior_4q) / 100.0
    return trend


def _cet1_pct(inp: Inputs) -> Optional[float]:
    """CET1 % from XBRL (r2).

    Returns as fraction.
    """
    if not inp.xbrl:
        return None

    cet1 = inp.xbrl.get("cet1")
    if cet1 is None or not math.isfinite(cet1):
        return None

    return cet1 / 100.0


def _provision_coverage(inp: Inputs) -> Optional[float]:
    """Provision coverage = provisions / GNPA.

    From XBRL (r2).
    """
    if not inp.xbrl:
        return None

    provisions = inp.xbrl.get("provisions")
    gnpa = inp.xbrl.get("gross_npa")

    if provisions is None or gnpa is None or gnpa <= 0:
        return None

    coverage = provisions / gnpa
    return coverage


def _deposit_vs_advance_growth(inp: Inputs) -> Optional[float]:
    """Deposits YoY growth - advances growth (BANK).

    From screener deposits and XBRL advances.
    """
    # Deposits YoY growth
    dep_series = inp.a_series("deposits")
    if dep_series.empty or len(dep_series) < 2:
        return None

    current_dep = dep_series.iloc[-1]
    prior_dep = dep_series.iloc[-2]

    if pd.isna(current_dep) or pd.isna(prior_dep) or prior_dep <= 0:
        return None

    dep_growth = (current_dep - prior_dep) / prior_dep

    # Advances from XBRL
    if not inp.xbrl or "advances" not in inp.xbrl:
        # Advances unknown, use deposits growth alone with note
        inp.notes.append("advances_unknown")
        return dep_growth

    adv_current = inp.xbrl.get("advances")
    # Get advances from prior year (if available)
    # For simplicity, we return just deposits growth
    # (full implementation would need historical XBRL)
    return dep_growth


def _fin_leverage(inp: Inputs) -> Optional[float]:
    """Financial leverage = borrowings / BVE (NBFC_FIN).

    Returns as ratio.
    """
    bor = inp.borrowings(-1)
    bve = inp.bve(-1)

    if bor is None or bve is None or bve <= 0:
        return None

    leverage = bor / bve
    return leverage


def _borrowing_cost(inp: Inputs) -> Optional[float]:
    """Borrowing cost = interest / avg borrowings (NBFC_FIN).

    Returns as fraction.
    """
    int_ttm = inp.ttm("interest")
    if int_ttm is None or int_ttm <= 0:
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

    cost = int_ttm / avg_bor
    return cost
