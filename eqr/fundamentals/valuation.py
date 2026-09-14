"""Pillar 6 — Valuation & Margin of Safety: WACC, DCF, comparable models, and fair value.

Implements: WACC, reverse DCF, two-stage DCF, EV/EBITDA, P/FCF, EPV, justified P/B, DDM,
band positions, and triangulation to fair value with margin of safety.

All valuations per share; net_debt in crore; mcap in crore.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import bisect

from .base import Inputs, MetricSet, ok, unknown, na


# --- Helper functions (no I/O, pure Python) ---


def wacc(beta: float, rf_pct: float, erp_pct: float, debt_weight: float, kd_pct: float,
         tax: float = 0.25, g_terminal: float = 0.05) -> float:
    """Weighted average cost of capital.

    Ke = rf + β × ERP
    WACC = Ke × (1 − debt_weight) + Kd × (1 − tax) × debt_weight
    floored at g_terminal + 3%

    Args:
        beta: unlevered or levered beta (assumed levered here; typically β ∈ [0.6, 1.6] clipped)
        rf_pct: risk-free rate as a fraction (e.g., 0.06 for 6%)
        erp_pct: equity risk premium (e.g., 0.055 for 5.5%)
        debt_weight: debt / (debt + equity) as a fraction [0, 1]
        kd_pct: cost of debt as a fraction (e.g., 0.08 for 8%)
        tax: corporate tax rate as a fraction (default 0.25)
        g_terminal: terminal growth rate for the floor (default 0.05)

    Returns:
        WACC as a fraction, floored at g_terminal + 0.03
    """
    ke = rf_pct + beta * erp_pct
    kd_after_tax = kd_pct * (1 - tax)
    w_c = wacc_value = ke * (1 - debt_weight) + kd_after_tax * debt_weight
    floor = g_terminal + 0.03
    return max(floor, wacc_value)


def implied_growth(ev: float, fcff0: float, wacc_val: float, years: int = 10,
                   g_terminal: float = 0.05) -> Optional[float]:
    """Reverse DCF: solve for g such that PV(FCFF) + TV(g_T) = EV.

    Two-stage: FCFF grows at rate g for `years`, then at g_terminal thereafter.
    TV = FCFF_0 × (1 + g)^years × (1 + g_terminal) / (wacc − g_terminal)

    Uses bisection on g ∈ [−0.5, 0.6]. Returns None if fcff0 ≤ 0 or ev ≤ 0.
    """
    if fcff0 <= 0 or ev <= 0 or wacc_val <= g_terminal:
        return None

    def pv_fcff(g: float) -> float:
        """Compute PV(FCFF) + TV(g_T) − EV; target is 0."""
        if g >= wacc_val:
            return 1e10  # Unrealistic (g >= WACC is invalid)
        # PV of stage 1: FCFF × Σ((1+g)/(1+WACC))^n for n=1..years
        pv_stage1 = 0.0
        for n in range(1, years + 1):
            pv_stage1 += fcff0 * ((1 + g) / (1 + wacc_val)) ** n
        # Terminal value
        fcff_terminal = fcff0 * ((1 + g) ** years) * (1 + g_terminal)
        tv = fcff_terminal / (wacc_val - g_terminal)
        pv_tv = tv / ((1 + wacc_val) ** years)
        return pv_stage1 + pv_tv - ev

    try:
        g_implied = bisect(pv_fcff, -0.5, 0.6, xtol=1e-6)
        return float(g_implied)
    except ValueError:
        return None


def dcf_two_stage(fcff0: float, g1: float, wacc_val: float, g_terminal: float = 0.05,
                  years1: int = 5, fade: int = 5) -> float:
    """Two-stage DCF with fade.

    Stage 1: FCFF grows at g1 for years1 years.
    Fade: growth linearly decays from g1 to g_terminal over `fade` years.
    Terminal: perpetual growth at g_terminal.

    Returns EV (enterprise value, before subtracting net_debt).
    """
    if wacc_val <= g_terminal:
        return 0.0

    pv = 0.0

    # Stage 1: explicit forecast at growth g1
    for t in range(1, years1 + 1):
        fcff_t = fcff0 * ((1 + g1) ** t)
        pv += fcff_t / ((1 + wacc_val) ** t)

    # Fade stage: linear decay from g1 to g_terminal
    g_curr = g1
    for t in range(years1 + 1, years1 + fade + 1):
        g_curr = g1 - (g1 - g_terminal) * (t - years1) / fade
        fcff_t = fcff0 * ((1 + g1) ** years1) * ((1 + g_curr) ** (t - years1))
        pv += fcff_t / ((1 + wacc_val) ** t)

    # Terminal value at end of fade
    fcff_terminal = fcff0 * ((1 + g1) ** years1) * ((1 + g_terminal) ** (fade + 1))
    tv = fcff_terminal / (wacc_val - g_terminal)
    pv_tv = tv / ((1 + wacc_val) ** (years1 + fade))
    pv += pv_tv

    return float(pv)


def epv(nopat: float, wacc_val: float) -> Optional[float]:
    """Earnings power value: no-growth perpetual.
    FV = NOPAT / WACC (no debt adjustment; this is EV, not equity value).
    """
    if nopat <= 0 or wacc_val <= 0:
        return None
    return float(nopat / wacc_val)


def own_band_position(series: pd.Series, current: float) -> Optional[float]:
    """Position of `current` value within historical band [min, max].

    Returns fraction in [0, 1]:
    - 0 = current is at or below the historical minimum
    - 1 = current is at or above the historical maximum
    - 0.5 = current is at the median

    Returns None if < 3 historical points.
    """
    if len(series) < 3:
        return None
    series = series.dropna().astype(float)
    if len(series) < 3:
        return None
    return float((series <= current).sum() / len(series))


def justified_pb(roe: float, coe: float, g: float) -> Optional[float]:
    """Justified P/B ratio.

    P/B* = (ROE − g) / (CoE − g)

    Returns None if CoE ≤ g (no-growth or negative growth cases where formula breaks down).
    """
    if coe <= g:
        return None
    pb = (roe - g) / (coe - g)
    return float(pb) if pb > 0 else None


def ddm(dps: float, coe: float, g: float) -> Optional[float]:
    """Dividend Discount Model: Gordon growth.

    FV = DPS / (CoE − g)

    Returns None if CoE ≤ g.
    """
    if coe <= g or dps <= 0:
        return None
    return float(dps / (coe - g))


def triangulate(models: dict[str, Optional[float]], weights: dict[str, float]) -> tuple:
    """Triangulate fair value from multiple models with profile-specific weights.

    Args:
        models: {model_name: fv_per_share | None}
        weights: {model_name: weight}

    Returns:
        (fv_base, fv_bull, fv_bear, dispersion)
        - fv_base = weighted median of available models
        - fv_bull = max of available models
        - fv_bear = min of available models
        - dispersion = (max − min) / median (None if < 2 models available)
    """
    available = {k: v for k, v in models.items() if v is not None and v > 0}
    if len(available) < 2:
        return None, None, None, None

    values = list(available.values())
    fv_bull = max(values)
    fv_bear = min(values)

    # Weighted median
    weighted_vals = sorted([(available.get(k), weights.get(k, 1.0)) for k in available.keys()],
                           key=lambda x: x[0])
    total_weight = sum(w for _, w in weighted_vals)
    cumsum = 0.0
    fv_base = fv_bull
    for val, w in weighted_vals:
        cumsum += w
        if cumsum >= total_weight / 2:
            fv_base = val
            break

    if fv_base > 0:
        dispersion = (fv_bull - fv_bear) / fv_base
    else:
        dispersion = None

    return fv_base, fv_bull, fv_bear, dispersion


def expected_return_band(ey: float, g_sust: float, pe_now: float, pe_median_10y: float,
                         vol: float) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Expected return band (informational only, never a score input).

    er_mid = earnings_yield + clip(g_sust, −10%, 20%) + clip(ln(pe_median_10y / pe_now) / 3, ±15%)
    er_lo, er_hi = er_mid ± max(10%, vol / √3)
    """
    if ey is None or g_sust is None or pe_now is None or pe_median_10y is None or vol is None:
        return None, None, None

    g_clip = max(-0.10, min(0.20, g_sust))
    if pe_median_10y > 0 and pe_now > 0:
        pe_ratio = pe_median_10y / pe_now
        pe_contrib = np.clip(np.log(pe_ratio) / 3, -0.15, 0.15)
    else:
        pe_contrib = 0.0

    er_mid = ey + g_clip + pe_contrib
    band_width = max(0.10, vol / np.sqrt(3))
    er_lo = er_mid - band_width
    er_hi = er_mid + band_width

    return float(er_lo), float(er_mid), float(er_hi)


# --- compute function ---

# fair-value triangulation weights per profile. EPV (no-growth earnings power) is the explicit
# BEAR anchor (fv_bear = min(models, EPV)) and is NOT inside the central median.
MODEL_WEIGHTS = {
    "GENERAL":     {"model_dcf_base": 0.40, "model_ev_ebitda": 0.35, "model_p_fcf": 0.25},
    "IT_SERVICES": {"model_dcf_base": 0.40, "model_ev_ebitda": 0.35, "model_p_fcf": 0.25},
    "PHARMA":      {"model_dcf_base": 0.40, "model_ev_ebitda": 0.35, "model_p_fcf": 0.25},
    "CYCLICAL":    {"model_dcf_base": 0.20, "model_ev_ebitda": 0.55, "model_p_fcf": 0.25},
    "BANK":        {"model_justified_pb": 0.70, "model_ddm": 0.30},
    "NBFC_FIN":    {"model_justified_pb": 0.70, "model_ddm": 0.30},
}
EV_EBITDA_CLIP = (4.0, 30.0)
P_FCF_CLIP = (5.0, 60.0)
NONFIN_MODELS = ("model_dcf_base", "model_dcf_bull", "model_dcf_bear", "model_ev_ebitda", "model_p_fcf", "model_epv")
FIN_MODELS = ("model_justified_pb", "model_ddm")


def _shares_cr(inp: Inputs) -> Optional[float]:
    eq = inp.a("equity_capital", -1)
    if eq is None or not inp.face_value or inp.face_value <= 0:
        return None
    return eq / inp.face_value


def _mcap(inp: Inputs, shares_cr: Optional[float]) -> Optional[float]:
    m = inp.feat.get("mcap_cr") if inp.feat else None
    if m is not None and m > 0:
        return float(m)
    if inp.price is not None and shares_cr:
        return float(inp.price * shares_cr)             # Rs x crore shares = crore rupees
    return None


def _wacc_from_inputs(inp: Inputs, mcap: Optional[float]) -> Optional[float]:
    beta = inp.feat.get("beta_250") if inp.feat else None
    b = 1.0 if beta is None else 0.67 * min(1.6, max(0.6, float(beta))) + 0.33
    rf, erp = inp.rf_pct / 100, inp.erp_pct / 100
    bor = inp.borrowings(-1) or 0.0
    bor_prev = inp.borrowings(-2)
    intr = inp.ttm("interest")
    if bor > 0 and intr is not None:
        avg = (bor + bor_prev) / 2 if bor_prev else bor
        kd = min(rf + 0.08, max(rf, intr / avg)) if avg > 0 else rf
    else:
        kd = rf
    if mcap is None or mcap <= 0:
        dw = 0.0
    else:
        dw = bor / (bor + mcap) if bor > 0 else 0.0
    return wacc(b, rf, erp, dw, kd, tax=inp.tax_rate, g_terminal=inp.g_terminal)


def _net_debt_series(inp: Inputs) -> pd.Series:
    """borrowings - investments per fiscal year (r1 proxy; XBRL cash in r2)."""
    bor = inp.a_series("borrowings")
    if bor.empty:
        bor = inp.a_series("borrowing")
    inv = inp.a_series("investments")
    if bor.empty:
        return pd.Series(dtype=float)
    return (bor - inv.reindex(bor.index).fillna(0.0)) if not inv.empty else bor


def _nopat_ttm(inp: Inputs) -> Optional[float]:
    op, dep = inp.ttm_op(), inp.ttm("depreciation")
    if op is None or dep is None:
        return None
    return float((op - dep) * (1 - inp.tax_rate))


def _own_multiple_median(inp: Inputs, kind: str) -> Optional[float]:
    """Median own EV/EBITDA (kind='ev_ebitda') or P/FCF (kind='p_fcf') over <= 10 fiscal years."""
    mh = inp.mcap_hist.dropna()
    if mh.empty:
        return None
    vals = []
    nd = _net_debt_series(inp)
    for d, mcap_y in mh.tail(10).items():
        if kind == "ev_ebitda":
            op = inp.annual["operating_profit"].get(d) if "operating_profit" in inp.annual.columns else None
            if op is None or pd.isna(op) or op <= 0:
                continue
            ev_y = mcap_y + float(nd.get(d, 0.0) if not nd.empty else 0.0)
            if ev_y > 0:
                vals.append(ev_y / float(op))
        else:
            fcf = inp.annual["free_cash_flow"].get(d) if "free_cash_flow" in inp.annual.columns else None
            if fcf is None or pd.isna(fcf) or fcf <= 0:
                continue
            vals.append(mcap_y / float(fcf))
    if len(vals) < 3:
        return None
    return float(np.median(vals))


def _band_position(inp: Inputs, kind: str, current: Optional[float]) -> Optional[float]:
    if current is None:
        return None
    mh = inp.mcap_hist.dropna()
    if mh.empty:
        return None
    hist = []
    nd = _net_debt_series(inp)
    for d, mcap_y in mh.tail(10).items():
        if kind == "pe":
            pat = inp.annual["net_profit"].get(d) if "net_profit" in inp.annual.columns else None
            if pat is not None and not pd.isna(pat) and pat > 0:
                hist.append(mcap_y / float(pat))
        else:
            op = inp.annual["operating_profit"].get(d) if "operating_profit" in inp.annual.columns else None
            if op is not None and not pd.isna(op) and op > 0:
                hist.append((mcap_y + float(nd.get(d, 0.0) if not nd.empty else 0.0)) / float(op))
    return own_band_position(pd.Series(hist, dtype=float), current) if len(hist) >= 3 else None


def compute(inp: Inputs, ctx: Optional[dict] = None) -> MetricSet:
    """Pillar 6 metrics. ctx: fundamental_growth, net_debt, wacc, nopat_ttm (from earlier modules)."""
    ctx = ctx or {}
    ms = MetricSet()
    asof = inp.latest_period()
    shares = _shares_cr(inp)
    mcap = _mcap(inp, shares)
    wacc_val = ctx.get("wacc") if ctx.get("wacc") is not None else _wacc_from_inputs(inp, mcap)
    ms.add(ok("wacc", wacc_val, inputs_as_of=asof))
    ms.add(ok("shares_cr", shares, unit="crore"))
    ms.add(ok("mcap_cr", mcap, unit="crore"))
    net_debt = ctx.get("net_debt")
    nd_note = ""
    if net_debt is None:
        nds = _net_debt_series(inp)
        net_debt = float(nds.iloc[-1]) if len(nds) else None
        nd_note = "net_debt_investments_proxy"
    pat_ttm = inp.ttm("net_profit")
    eps_ttm = inp.ttm("eps_in_rs")
    bve = inp.bve(-1)
    bvps = bve / shares if bve is not None and shares else None
    ms.add(ok("bvps", bvps, unit="rupees"))
    ms.add(ok("eps_ttm", eps_ttm, unit="rupees"))
    pe_now = mcap / pat_ttm if mcap and pat_ttm and pat_ttm > 0 else None
    pb_now = mcap / bve if mcap and bve and bve > 0 else None
    ms.add(ok("pe_ttm", pe_now))
    ms.add(ok("pb", pb_now))
    ms.add(ok("earnings_yield", pat_ttm / mcap if mcap and pat_ttm is not None else None))
    payout = inp.a("dividend_payout_pct", -1)
    ms.add(ok("div_yield", (payout / 100 * pat_ttm) / mcap if mcap and pat_ttm and pat_ttm > 0 and payout is not None else None))
    ms.add(ok("pe_band_pos_10y", _band_position(inp, "pe", pe_now), note="own 10y FY P/E band"))

    models: dict[str, Optional[float]] = {}
    if not inp.is_financial:
        ev = mcap + net_debt if mcap is not None and net_debt is not None else None
        ms.add(ok("ev", ev, unit="crore", note=nd_note))
        fcf_hist = inp.a_series("free_cash_flow").dropna().tail(3)
        fcf0 = float(fcf_hist.median()) if len(fcf_hist) else None
        nopat = ctx.get("nopat_ttm") if ctx.get("nopat_ttm") is not None else _nopat_ttm(inp)
        note = ""
        if (fcf0 is None or fcf0 <= 0) and nopat is not None and nopat > 0:
            fcf0, note = nopat * 0.5, "fcff_from_nopat"
        ms.add(ok("fcf0", fcf0, unit="crore", note=note))
        ms.add(ok("nopat_ttm_val", nopat, unit="crore"))
        ms.add(ok("fcf_yield", (float(fcf_hist.median()) / mcap) if len(fcf_hist) and mcap else None))
        ig = implied_growth(ev, fcf0, wacc_val, 10, inp.g_terminal) if ev and fcf0 and fcf0 > 0 and wacc_val else None
        ms.add(ok("implied_growth", ig))
        fg = ctx.get("fundamental_growth")
        if fg is None:
            s5 = inp.sales(-1); s0 = inp.sales(-6)
            fg = (s5 / s0) ** 0.2 - 1 if s5 and s0 and s5 > 0 and s0 > 0 else 0.08
            fg = min(fg, 0.15)
        g1 = max(-0.05, min(0.25, fg))
        ms.add(ok("dcf_g1", g1))
        if fcf0 and fcf0 > 0 and wacc_val and shares and net_debt is not None:
            for name, g in (("model_dcf_base", g1), ("model_dcf_bull", g1 + 0.05), ("model_dcf_bear", g1 - 0.05)):
                ev_m = dcf_two_stage(fcf0, g, wacc_val, inp.g_terminal, 5, 5)
                eq = ev_m - net_debt
                models[name] = eq / shares if eq > 0 else None
        else:
            for name in ("model_dcf_base", "model_dcf_bull", "model_dcf_bear"):
                models[name] = None
        # normalised EV/EBITDA
        mult = _own_multiple_median(inp, "ev_ebitda")
        opm = inp.a_series("operating_profit") / inp.a_series("sales").replace(0, np.nan) if "operating_profit" in inp.annual.columns and "sales" in inp.annual.columns else pd.Series(dtype=float)
        opm = opm.dropna().tail(5)
        sales_ttm = inp.ttm_sales()
        if mult is not None and len(opm) and sales_ttm and shares and net_debt is not None:
            m = min(EV_EBITDA_CLIP[1], max(EV_EBITDA_CLIP[0], mult))
            eq = m * float(opm.median()) * sales_ttm - net_debt
            models["model_ev_ebitda"] = eq / shares if eq > 0 else None
            ms.add(ok("own_ev_ebitda_median", mult))
        else:
            models["model_ev_ebitda"] = None
            ms.add(unknown("own_ev_ebitda_median", "needs 3 FY with EBITDA > 0 and mcap history"))
        # P/FCF
        pm = _own_multiple_median(inp, "p_fcf")
        if pm is not None and len(fcf_hist) and float(fcf_hist.median()) > 0 and shares:
            m = min(P_FCF_CLIP[1], max(P_FCF_CLIP[0], pm))
            models["model_p_fcf"] = m * float(fcf_hist.median()) / shares
            ms.add(ok("own_p_fcf_median", pm))
        else:
            models["model_p_fcf"] = None
            ms.add(unknown("own_p_fcf_median", "needs 3 FY with FCF > 0 and mcap history"))
        # EPV
        if nopat and nopat > 0 and wacc_val and shares and net_debt is not None:
            eq = epv(nopat, wacc_val) - net_debt
            models["model_epv"] = eq / shares if eq > 0 else None
        else:
            models["model_epv"] = None
        for name in FIN_MODELS:
            ms.add(na(name, unit="rupees"))
        ms.add(na("pb_vs_justified"))
        op_ttm = inp.ttm_op()
        ev_ebitda_now = ev / op_ttm if ev and op_ttm and op_ttm > 0 else None
        ms.add(ok("ev_ebitda_ttm", ev_ebitda_now))
        ms.add(ok("ev_ebitda_band_pos", _band_position(inp, "ev_ebitda", ev_ebitda_now), note="own 10y FY EV/EBITDA band"))
    else:
        for name in ("ev", "fcf0", "implied_growth", "dcf_g1", "fcf_yield", "ev_ebitda_band_pos", "ev_ebitda_ttm"):
            ms.add(na(name))
        for name in NONFIN_MODELS:
            ms.add(na(name, unit="rupees"))
        bve_prev = inp.bve(-2)
        roe = pat_ttm / ((bve + bve_prev) / 2) if pat_ttm is not None and bve and bve_prev and bve > 0 and bve_prev > 0 else (pat_ttm / bve if pat_ttm is not None and bve and bve > 0 else None)
        beta = inp.feat.get("beta_250") if inp.feat else None
        b = 1.0 if beta is None else 0.67 * min(1.6, max(0.6, float(beta))) + 0.33
        coe = inp.rf_pct / 100 + b * inp.erp_pct / 100
        ms.add(ok("coe", coe))
        retention = 1 - (payout / 100) if payout is not None else 1.0
        retention = min(1.0, max(0.0, retention))
        g = min(retention * roe, coe - 0.01) if roe is not None else None
        pbj = justified_pb(roe, coe, g) if roe is not None and g is not None else None
        ms.add(ok("justified_pb", pbj))
        models["model_justified_pb"] = pbj * bvps if pbj and bvps else None
        if payout is not None and payout >= 30 and eps_ttm and eps_ttm > 0 and g is not None:
            models["model_ddm"] = ddm(eps_ttm * payout / 100, coe, g)
        else:
            models["model_ddm"] = None
        ms.add(ok("pb_vs_justified", pb_now / pbj if pb_now and pbj else None))
    for name, v in models.items():
        ms.add(ok(name, v, unit="rupees") if v is not None else unknown(name, "model inputs missing", unit="rupees"))
    weights = MODEL_WEIGHTS.get(inp.profile, MODEL_WEIGHTS["GENERAL"])
    tri_models = {k: v for k, v in models.items() if k in weights}
    fv_base, fv_bull, fv_bear, disp = triangulate(tri_models, weights)
    avail = {k: v for k, v in tri_models.items() if v is not None and v > 0}
    if fv_base is None and len(avail) == 1:                 # single model (e.g. NBFC without DDM)
        only = next(iter(avail.values()))
        fv_base = fv_bull = fv_bear = only
        disp = None
    # dispersion is measured across the CENTRAL models; EPV is the explicit no-growth bear anchor
    central = {k: v for k, v in avail.items() if k != "model_epv"}
    if len(central) >= 2:
        cv = sorted(central.values())
        med = float(np.median(cv))
        disp = (cv[-1] - cv[0]) / med if med > 0 else None
    elif len(central) == 1 and len(avail) >= 2:
        disp = None
    if fv_base is not None and not inp.is_financial:
        # bear anchor = min(central models, dcf bear, EPV); bull = max(central models, dcf bull)
        highs = [v for k, v in models.items() if v is not None and k not in ("model_dcf_bear", "model_epv")]
        fv_bull = max(highs) if highs else fv_bull
        lows = [v for k, v in models.items() if v is not None and k != "model_dcf_bull"]
        fv_bear = min(lows) if lows else fv_bear
    ms.add(ok("fv_base", fv_base, unit="rupees"))
    ms.add(ok("fv_bull", fv_bull, unit="rupees"))
    ms.add(ok("fv_bear", fv_bear, unit="rupees"))
    ms.add(ok("val_dispersion", disp))
    ms.add(ok("n_models", float(len(avail)), unit="count"))
    mos = fv_base / inp.price - 1 if fv_base and inp.price and inp.price > 0 else None
    ms.add(ok("mos_base", mos))
    # expected-return band (informational)
    vol = inp.feat.get("vol_250") if inp.feat else None
    pe_hist = []
    for d, mcap_y in inp.mcap_hist.dropna().tail(10).items():
        pat = inp.annual["net_profit"].get(d) if "net_profit" in inp.annual.columns else None
        if pat is not None and not pd.isna(pat) and pat > 0:
            pe_hist.append(mcap_y / float(pat))
    ey = pat_ttm / mcap if mcap and pat_ttm is not None else None
    fg_er = ctx.get("fundamental_growth")
    lo, mid, hi = expected_return_band(ey, fg_er, pe_now, float(np.median(pe_hist)) if len(pe_hist) >= 3 else None, vol)
    ms.add(ok("er_lo", lo)); ms.add(ok("er_mid", mid)); ms.add(ok("er_hi", hi))
    return ms
