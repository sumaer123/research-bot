"""Pillar 3: Earnings Quality & Forensic Accounting metrics.

Non-financial earningsquality metrics: cash flow backing (CFO/PAT), FCF conversion,
Sloan accruals, Beneish M-score (misstatement detector), other-income share, working capital
dynamics, depreciation policy consistency, reserve leakage, and tax integrity.

Beneish M-score (2012 paper, 4.679 TATA coefficient): −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI
+ 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI.
- Real components (r1): DSRI, SGI, DEPI, TATA, LVGI (5 + 2 proxies at most = 7 → compute)
- Proxy components: GMI (OPM-based), AQI (1 − (other_assets+fixed_assets)/TA)
- SGAI: UNKNOWN (SG&A not in screener); not counted when omitted
- Rule: compute when ≥6 components present (at most 2 proxies); abstain otherwise
- Beneish level: M < −2.22 → 100 clean; −2.22 to −1.78 → 50 watch; > −1.78 → 0 flag
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .base import Inputs, Metric, MetricSet, ok, unknown, na


def compute(inp: Inputs, ctx: dict | None = None) -> MetricSet:
    """Compute Pillar 3 forensic earnings quality metrics.

    For financial profiles (BANK/NBFC_FIN), returns NA for non-financial metrics.
    All 5-year aggregations use at most 5 annual periods (inp.annual[-5:]).
    """
    out = MetricSet()

    # Financial profile check
    is_fin = inp.is_financial
    is_bank = inp.is_bank

    # --- Non-financial metrics for non-financial profiles ---

    if not is_fin:
        # CFO-to-PAT and FCF conversions (5-year)
        out.add(_cfo_to_pat_5y(inp))
        out.add(_fcf_conversion_5y(inp))
        out.add(_cfo_to_ebitda_5y(inp))
    else:
        out.add(na("cfo_to_pat_5y"))
        out.add(na("fcf_conversion_5y"))
        out.add(na("cfo_to_ebitda_5y"))

    # Accruals (Sloan and Balance Sheet) - non-financial only
    if not is_fin:
        out.add(_accrual_ratio_sloan(inp))
        out.add(_accrual_ratio_sloan_abs(inp))
        out.add(_accrual_ratio_sloan_prev(inp))
        out.add(_accrual_ratio_bs_abs(inp))
    else:
        out.add(na("accrual_ratio_sloan"))
        out.add(na("accrual_ratio_sloan_abs"))
        out.add(na("accrual_ratio_sloan_prev"))
        out.add(na("accrual_ratio_bs_abs"))

    # Beneish M-score and forensics - non-financial only
    if not is_fin:
        bm, bc, note = _beneish_m_score(inp)
        out.add(ok("beneish_m", bm, note=note) if bm is not None else unknown("beneish_m", note=note))
        out.add(ok("beneish_components", bc, note=f"components_counted={note.split('=')[-1] if '=' in note else ''}")
                if bc is not None else unknown("beneish_components", note=note))
        out.add(_beneish_level(bm))
        out.add(_beneish_m_prev(inp))
    else:
        out.add(na("beneish_m"))
        out.add(na("beneish_components"))
        out.add(na("beneish_level"))
        out.add(na("beneish_m_prev"))

    # Other income and tax metrics - all profiles
    out.add(_other_income_share(inp))
    out.add(_cash_tax_gap(inp))

    # Capital working items - non-financial only
    if not is_fin:
        out.add(_capitalisation_proxy(inp))
        out.add(_receivable_days_delta_3y(inp))
        out.add(_inventory_days_delta_3y(inp))
        out.add(_payable_days_delta_3y(inp))
        out.add(_ccc_delta_3y(inp))
        out.add(_depreciation_rate_cv_5y(inp))
        out.add(_reserves_leakage_5y(inp))
    else:
        out.add(na("capitalisation_proxy"))
        out.add(na("receivable_days_delta_3y"))
        out.add(na("inventory_days_delta_3y"))
        out.add(na("payable_days_delta_3y"))
        out.add(na("ccc_delta_3y"))
        out.add(na("depreciation_rate_cv_5y"))
        out.add(na("reserves_leakage_5y"))

    # Audit opinion - r2, from XBRL
    out.add(_audit_opinion_clean(inp))

    # Financial profile metrics (banks/NBFCs)
    if is_fin:
        out.add(_credit_cost(inp))
        out.add(_gnpa_delta_4q_neg(inp))
    else:
        out.add(na("credit_cost"))
        out.add(na("gnpa_delta_4q_neg"))

    return out


def _cfo_to_pat_5y(inp: Inputs) -> Metric:
    """Σ CFO / Σ PAT over 5 annual years (or fewer if available)."""
    a = inp.annual
    if a.empty or "cash_from_operating_activity" not in a.columns or "net_profit" not in a.columns:
        return unknown("cfo_to_pat_5y", "missing CFO or PAT")
    cfo_s = a["cash_from_operating_activity"].astype(float).tail(5)
    pat_s = a["net_profit"].astype(float).tail(5)
    cfo_sum = cfo_s.sum()
    pat_sum = pat_s.sum()
    if pat_sum <= 0 or cfo_sum != cfo_sum:  # NaN check
        return unknown("cfo_to_pat_5y", "ΣPAT ≤ 0 or ΣCFO missing")
    return ok("cfo_to_pat_5y", cfo_sum / pat_sum, inputs_as_of=inp.latest_period())


def _fcf_conversion_5y(inp: Inputs) -> Metric:
    """Σ FCF / Σ PAT over 5 annual years."""
    a = inp.annual
    if a.empty or "free_cash_flow" not in a.columns or "net_profit" not in a.columns:
        return unknown("fcf_conversion_5y", "missing FCF or PAT")
    fcf_s = a["free_cash_flow"].astype(float).tail(5)
    pat_s = a["net_profit"].astype(float).tail(5)
    fcf_sum = fcf_s.sum()
    pat_sum = pat_s.sum()
    if pat_sum <= 0 or fcf_sum != fcf_sum:
        return unknown("fcf_conversion_5y", "ΣPAT ≤ 0 or ΣFCF missing")
    return ok("fcf_conversion_5y", fcf_sum / pat_sum, inputs_as_of=inp.latest_period())


def _cfo_to_ebitda_5y(inp: Inputs) -> Metric:
    """Σ CFO / Σ Operating Profit over 5 annual years."""
    a = inp.annual
    if a.empty or "cash_from_operating_activity" not in a.columns:
        return unknown("cfo_to_ebitda_5y", "missing CFO")
    cfo_s = a["cash_from_operating_activity"].astype(float).tail(5)
    # EBITDA ≈ operating_profit (screener provides this)
    op_s = a.get("operating_profit", a.get("financing_profit", pd.Series()))
    if op_s.empty:
        return unknown("cfo_to_ebitda_5y", "missing operating_profit")
    op_s = op_s.astype(float).tail(5)
    op_sum = op_s.sum()
    cfo_sum = cfo_s.sum()
    if op_sum <= 0 or cfo_sum != cfo_sum:
        return unknown("cfo_to_ebitda_5y", "Σoperating_profit ≤ 0 or ΣCFO missing")
    return ok("cfo_to_ebitda_5y", cfo_sum / op_sum, inputs_as_of=inp.latest_period())


def _accrual_ratio_sloan(inp: Inputs) -> Metric:
    """(PAT − CFO) / avg total_assets, latest FY. Signed (negative is good)."""
    a = inp.annual
    if a.empty or len(a) < 1:
        return unknown("accrual_ratio_sloan", "no annual data")
    pat = inp.a("net_profit", -1)
    cfo = inp.a("cash_from_operating_activity", -1)
    ta = inp.a("total_assets", -1)
    if pat is None or cfo is None or ta is None or ta <= 0:
        return unknown("accrual_ratio_sloan", "missing inputs")
    accrual = (pat - cfo) / ta
    if not math.isfinite(accrual):
        return unknown("accrual_ratio_sloan", "non-finite result")
    return ok("accrual_ratio_sloan", accrual, inputs_as_of=inp.latest_period())


def _accrual_ratio_sloan_abs(inp: Inputs) -> Metric:
    """Absolute value of accrual_ratio_sloan."""
    m = _accrual_ratio_sloan(inp)
    if m.status != "OK" or m.value is None:
        return unknown("accrual_ratio_sloan_abs", note=m.note)
    return ok("accrual_ratio_sloan_abs", abs(m.value), inputs_as_of=m.inputs_as_of, note=m.note)


def _accrual_ratio_sloan_prev(inp: Inputs) -> Metric:
    """Accrual ratio for the previous FY (informational)."""
    a = inp.annual
    if a.empty or len(a) < 2:
        return unknown("accrual_ratio_sloan_prev", "insufficient history")
    pat = inp.a("net_profit", -2)
    cfo = inp.a("cash_from_operating_activity", -2)
    ta = inp.a("total_assets", -2)
    if pat is None or cfo is None or ta is None or ta <= 0:
        return unknown("accrual_ratio_sloan_prev", "missing inputs")
    accrual = (pat - cfo) / ta
    if not math.isfinite(accrual):
        return unknown("accrual_ratio_sloan_prev", "non-finite result")
    return ok("accrual_ratio_sloan_prev", accrual, inputs_as_of=inp.latest_period(), note="informational")


def _accrual_ratio_bs_abs(inp: Inputs) -> Metric:
    """ΔNOA / avg NOA; NOA = (TA − cash) − (TL − borrowings). Requires XBRL (r2)."""
    # For now, since XBRL is not populated in the live data yet, return UNKNOWN
    return unknown("accrual_ratio_bs_abs", "xbrl_required")


def _beneish_m_score(inp: Inputs) -> tuple[Optional[float], Optional[float], str]:
    """Beneish M-score: −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI.

    Returns (m_score, component_count, note_str).
    Rule: compute when ≥6 components present (at most 2 proxies); abstain otherwise.
    Components: DSRI (real), GMI (proxy), AQI (proxy), SGI (real), DEPI (real), SGAI (unknown),
                TATA (real), LVGI (real).
    """
    a = inp.annual
    if a.empty or len(a) < 2:
        return None, None, "beneish_abstain_insufficient_history"

    # Get t and t-1 values
    pat_t = inp.a("net_profit", -1)
    cfo_t = inp.a("cash_from_operating_activity", -1)
    sales_t = inp.sales(-1)
    sales_t1 = inp.sales(-2)
    op_t = inp.op(-1)
    op_t1 = inp.op(-2)
    dep_t = inp.a("depreciation", -1)
    dep_t1 = inp.a("depreciation", -2)
    fa_t = inp.a("fixed_assets", -1)
    fa_t1 = inp.a("fixed_assets", -2)
    ta_t = inp.a("total_assets", -1)
    ta_t1 = inp.a("total_assets", -2)
    oa_t = inp.a("other_assets", -1)
    bor_t = inp.borrowings(-1)
    bor_t1 = inp.borrowings(-2)
    ol_t = inp.a("other_liabilities", -1)
    ol_t1 = inp.a("other_liabilities", -2)

    components = []
    proxies = 0
    note_parts = []

    # DSRI = debtor_days_t / debtor_days_t-1 (real)
    dd_t = inp.a("debtor_days", -1)
    dd_t1 = inp.a("debtor_days", -2)
    if dd_t is not None and dd_t1 is not None and dd_t1 > 0:
        dsri = dd_t / dd_t1
        if math.isfinite(dsri):
            components.append(dsri)

    # GMI = OPM_t-1 / OPM_t (proxy: operating profit / sales)
    if op_t1 is not None and op_t is not None and sales_t is not None and sales_t1 is not None and sales_t > 0 and sales_t1 > 0:
        opm_t = op_t / sales_t
        opm_t1 = op_t1 / sales_t1
        if opm_t > 0:
            gmi = opm_t1 / opm_t
            if math.isfinite(gmi):
                components.append(gmi)
                proxies += 1

    # AQI = (1 − (other_assets_t + fixed_assets_t)/TA_t) / (same t-1) (proxy)
    oa_t1 = inp.a("other_assets", -2)
    if oa_t is not None and fa_t is not None and ta_t is not None and ta_t > 0 and \
       oa_t1 is not None and fa_t1 is not None and ta_t1 is not None and ta_t1 > 0:
        aqi_t = 1.0 - (oa_t + fa_t) / ta_t
        aqi_t1 = 1.0 - (oa_t1 + fa_t1) / ta_t1
        if aqi_t1 > 0:
            aqi = aqi_t / aqi_t1
            if math.isfinite(aqi):
                components.append(aqi)
                proxies += 1

    # SGI = sales_t / sales_t-1 (real)
    if sales_t is not None and sales_t1 is not None and sales_t1 > 0:
        sgi = sales_t / sales_t1
        if math.isfinite(sgi):
            components.append(sgi)

    # DEPI = (dep_t-1 / (dep_t-1 + fixed_assets_t-1)) / (dep_t / (dep_t + fixed_assets_t)) (real)
    if dep_t1 is not None and fa_t1 is not None and dep_t is not None and fa_t is not None:
        depr_rate_t1 = dep_t1 / (dep_t1 + fa_t1) if (dep_t1 + fa_t1) > 0 else None
        depr_rate_t = dep_t / (dep_t + fa_t) if (dep_t + fa_t) > 0 else None
        if depr_rate_t1 is not None and depr_rate_t is not None and depr_rate_t > 0:
            depi = depr_rate_t1 / depr_rate_t
            if math.isfinite(depi):
                components.append(depi)

    # SGAI: UNKNOWN (no SG&A in screener) - not counted, but note this
    note_parts.append("sgai_unknown")

    # TATA = (PAT_t − CFO_t) / total_assets_t (real)
    if pat_t is not None and cfo_t is not None and ta_t is not None and ta_t > 0:
        tata = (pat_t - cfo_t) / ta_t
        if math.isfinite(tata):
            components.append(tata)

    # LVGI = ((borrowings_t + other_liabilities_t) / total_assets_t) / (same t-1) (real)
    if bor_t is not None and ol_t is not None and ta_t is not None and ta_t > 0 and \
       bor_t1 is not None and ol_t1 is not None and ta_t1 is not None and ta_t1 > 0:
        lvgi_t = (bor_t + ol_t) / ta_t
        lvgi_t1 = (bor_t1 + ol_t1) / ta_t1
        if lvgi_t1 > 0:
            lvgi = lvgi_t / lvgi_t1
            if math.isfinite(lvgi):
                components.append(lvgi)

    # Check rule: ≥6 components and at most 2 proxies
    if len(components) < 6:
        return None, None, f"beneish_abstain_{len(components)}"
    if proxies > 2:
        return None, None, f"beneish_abstain_proxies={proxies}"

    # Compute M-score
    m = -4.84
    m += 0.92 * components[0] if len(components) > 0 else 0  # DSRI
    m += 0.528 * components[1] if len(components) > 1 else 0  # GMI
    m += 0.404 * components[2] if len(components) > 2 else 0  # AQI
    m += 0.892 * components[3] if len(components) > 3 else 0  # SGI
    m += 0.115 * components[4] if len(components) > 4 else 0  # DEPI
    # SGAI skipped (index 5 shifts)
    m += 4.679 * components[5] if len(components) > 5 else 0  # TATA (index 5 since SGAI is skipped)
    m -= 0.327 * components[6] if len(components) > 6 else 0  # LVGI (index 6)

    note_str = f"beneish_proxies={proxies},components={len(components)}"
    return m, len(components), note_str


def _beneish_level(m_score: Optional[float]) -> Metric:
    """Beneish level: < −2.22 → 100 clean; −2.22 to −1.78 → 50 watch; > −1.78 → 0 flag."""
    if m_score is None:
        return unknown("beneish_level", "beneish_m unknown")
    if m_score < -2.22:
        return ok("beneish_level", 100.0)
    elif m_score <= -1.78:
        return ok("beneish_level", 50.0)
    else:
        return ok("beneish_level", 0.0)


def _beneish_m_prev(inp: Inputs) -> Metric:
    """Beneish M-score for the prior FY pair (t-1, t-2)."""
    # This is informational and requires computing over the prior year's pair
    # For now, we return a placeholder as it requires two-year lookback
    return unknown("beneish_m_prev", "not implemented")


def _other_income_share(inp: Inputs) -> Metric:
    """other_income / profit_before_tax (TTM). UNKNOWN if PBT ≤ 0."""
    oi = inp.ttm("other_income")
    pbt = inp.ttm("profit_before_tax")
    if oi is None or pbt is None or pbt <= 0:
        return unknown("other_income_share", "missing OI or PBT ≤ 0")
    return ok("other_income_share", oi / pbt, inputs_as_of=inp.latest_period())


def _cash_tax_gap(inp: Inputs) -> Metric:
    """|tax_pct/100 − tax_rate| averaged over last 3 FYs. UNKNOWN if tax_pct missing."""
    a = inp.annual
    if a.empty or "tax_pct" not in a.columns:
        return unknown("cash_tax_gap", "missing tax_pct")
    tax_pcts = a["tax_pct"].astype(float).tail(3)
    valid = tax_pcts.dropna()
    if len(valid) == 0:
        return unknown("cash_tax_gap", "all tax_pct missing")
    # statutory rate is 25% (from inp.tax_rate = 0.25)
    gaps = [abs(tp / 100 - inp.tax_rate) for tp in valid]
    avg_gap = np.mean(gaps)
    return ok("cash_tax_gap", avg_gap, inputs_as_of=inp.latest_period())


def _capitalisation_proxy(inp: Inputs) -> Metric:
    """CWIP / (fixed_assets + CWIP)."""
    cwip = inp.a("cwip", -1)
    fa = inp.a("fixed_assets", -1)
    if cwip is None or fa is None:
        return unknown("capitalisation_proxy", "missing CWIP or fixed_assets")
    denom = fa + cwip
    if denom <= 0:
        return unknown("capitalisation_proxy", "denominator ≤ 0")
    return ok("capitalisation_proxy", cwip / denom, inputs_as_of=inp.latest_period())


def _receivable_days_delta_3y(inp: Inputs) -> Metric:
    """debtor_days now − 3 years ago (days delta)."""
    dd_now = inp.a("debtor_days", -1)
    dd_3y = inp.a("debtor_days", -4)  # approximately 3 years (4 rows back)
    if dd_now is None or dd_3y is None:
        return unknown("receivable_days_delta_3y", "missing debtor_days history")
    delta = dd_now - dd_3y
    return ok("receivable_days_delta_3y", delta, inputs_as_of=inp.latest_period())


def _inventory_days_delta_3y(inp: Inputs) -> Metric:
    """inventory_days now − 3 years ago."""
    id_now = inp.a("inventory_days", -1)
    id_3y = inp.a("inventory_days", -4)
    if id_now is None or id_3y is None:
        return unknown("inventory_days_delta_3y", "missing inventory_days history")
    delta = id_now - id_3y
    return ok("inventory_days_delta_3y", delta, inputs_as_of=inp.latest_period())


def _payable_days_delta_3y(inp: Inputs) -> Metric:
    """days_payable now − 3 years ago. (Note: sign reversed in scoring; stretching payables is a warning)."""
    pd_now = inp.a("days_payable", -1)
    pd_3y = inp.a("days_payable", -4)
    if pd_now is None or pd_3y is None:
        return unknown("payable_days_delta_3y", "missing days_payable history")
    delta = pd_now - pd_3y
    return ok("payable_days_delta_3y", delta, inputs_as_of=inp.latest_period())


def _ccc_delta_3y(inp: Inputs) -> Metric:
    """cash_conversion_cycle now − 3 years ago (informational)."""
    ccc_now = inp.a("cash_conversion_cycle", -1)
    ccc_3y = inp.a("cash_conversion_cycle", -4)
    if ccc_now is None or ccc_3y is None:
        return unknown("ccc_delta_3y", "missing CCC history")
    delta = ccc_now - ccc_3y
    return ok("ccc_delta_3y", delta, inputs_as_of=inp.latest_period(), note="informational")


def _depreciation_rate_cv_5y(inp: Inputs) -> Metric:
    """σ/mean of depreciation / fixed_assets over 5 FYs (policy games flag)."""
    a = inp.annual
    if a.empty or "depreciation" not in a.columns or "fixed_assets" not in a.columns:
        return unknown("depreciation_rate_cv_5y", "missing depreciation or fixed_assets")
    dep_s = a["depreciation"].astype(float).tail(5)
    fa_s = a["fixed_assets"].astype(float).tail(5)
    if len(dep_s) < 2:
        return unknown("depreciation_rate_cv_5y", "insufficient history")
    rates = []
    for d, f in zip(dep_s, fa_s):
        if f is not None and f > 0 and d is not None:
            rates.append(d / f)
    if len(rates) < 2:
        return unknown("depreciation_rate_cv_5y", "insufficient valid rates")
    mean_rate = np.mean(rates)
    std_rate = np.std(rates)
    if mean_rate <= 0:
        return unknown("depreciation_rate_cv_5y", "mean rate ≤ 0")
    cv = std_rate / mean_rate
    return ok("depreciation_rate_cv_5y", cv, inputs_as_of=inp.latest_period())


def _reserves_leakage_5y(inp: Inputs) -> Metric:
    """(Σ retained PAT − Δreserves) / Σ retained PAT over 5 FYs.

    Retained PAT = PAT × (1 − payout% / 100).
    If Σ retained ≤ 0, return UNKNOWN.
    Result clipped to [−1, 1].
    """
    a = inp.annual
    if a.empty or "net_profit" not in a.columns or "reserves" not in a.columns or "dividend_payout_pct" not in a.columns:
        return unknown("reserves_leakage_5y", "missing PAT, reserves, or payout")

    pat_s = a["net_profit"].astype(float).tail(5)
    res_s = a["reserves"].astype(float).tail(5)
    payout_s = a["dividend_payout_pct"].astype(float).tail(5)

    retained_pat = []
    for pat, payout in zip(pat_s, payout_s):
        if pat is not None and payout is not None and math.isfinite(pat) and math.isfinite(payout):
            retained = pat * (1 - payout / 100)
            retained_pat.append(retained)

    if len(retained_pat) == 0:
        return unknown("reserves_leakage_5y", "no valid retained PAT")

    sum_retained = sum(retained_pat)
    if sum_retained <= 0:
        return unknown("reserves_leakage_5y", "Σ retained PAT ≤ 0")

    # Δreserves over 5 years
    delta_reserves = 0.0
    for i in range(len(res_s)):
        if i > 0:
            if res_s.iloc[i] is not None and res_s.iloc[i-1] is not None and \
               math.isfinite(res_s.iloc[i]) and math.isfinite(res_s.iloc[i-1]):
                delta_reserves += res_s.iloc[i] - res_s.iloc[i-1]

    # Final calculation: (Σ retained PAT − Δreserves) / Σ retained PAT
    leakage = (sum_retained - delta_reserves) / sum_retained
    leakage = np.clip(leakage, -1.0, 1.0)

    return ok("reserves_leakage_5y", leakage, inputs_as_of=inp.latest_period())


def _audit_opinion_clean(inp: Inputs) -> Metric:
    """Binary: 1 when unmodified audit opinion, 0 otherwise. Requires XBRL (r2)."""
    xbrl = inp.xbrl or {}
    auditor_opinion = xbrl.get("auditor_opinion")
    if auditor_opinion is None:
        return unknown("audit_opinion_clean", "xbrl_required")
    # Assume "unmodified" or "clean" → 1, anything else → 0
    is_clean = 1.0 if "unmodified" in str(auditor_opinion).lower() or "clean" in str(auditor_opinion).lower() else 0.0
    return ok("audit_opinion_clean", is_clean, inputs_as_of=inp.latest_period())


def _credit_cost(inp: Inputs) -> Metric:
    """For banks/NBFCs: provisions / avg advances (XBRL, r2)."""
    xbrl = inp.xbrl or {}
    provisions = xbrl.get("provisions")
    advances = xbrl.get("advances")
    if provisions is None or advances is None:
        return unknown("credit_cost", "xbrl_required")
    if advances <= 0:
        return unknown("credit_cost", "advances ≤ 0")
    return ok("credit_cost", provisions / advances, inputs_as_of=inp.latest_period())


def _gnpa_delta_4q_neg(inp: Inputs) -> Metric:
    """gnpa_pct now − 4 quarters ago (pp). UNKNOWN 'xbrl_required' if quarterly unavailable."""
    q = inp.quarterly
    if q.empty or "gross_npa_pct" not in q.columns or len(q) < 4:
        return unknown("gnpa_delta_4q_neg", "xbrl_required")
    gnpa_now = inp.q("gross_npa_pct", -1)
    gnpa_4q = inp.q("gross_npa_pct", -4)
    if gnpa_now is None or gnpa_4q is None:
        return unknown("gnpa_delta_4q_neg", "missing quarterly GNPA")
    delta = gnpa_now - gnpa_4q
    return ok("gnpa_delta_4q_neg", delta, inputs_as_of=inp.latest_period())
