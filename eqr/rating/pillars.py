"""Component catalogue (the six pillars as data) and the pillar scorer.

Scoring rules (methodology plan §3.2):
- pct components: 0..100 percentile of sign x value within the (as_of, profile) group (>= 8 names) else universe;
- map components: piecewise-linear absolute map (x ascending), clipped at both ends;
- binary components: 100 when the condition is good, 0 when bad;
- UNKNOWN components take the group prior (median score of names that do know it), never dropped,
  never renormalised; a pillar with < 50% of applicable weight known is UNKNOWN and takes its prior.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .model import Component, ComponentScore, PillarScore, OK, UNKNOWN, NA
from .sector import PILLARS, FINANCIAL, BANK, NBFC_FIN, GENERAL, IT_SERVICES, PHARMA, CYCLICAL

NONFIN = frozenset({GENERAL, IT_SERVICES, PHARMA, CYCLICAL})
FIN = frozenset(FINANCIAL)
ALL = frozenset({"ALL"})


def _c(name, pillar, kind, sign=+1, weight=1.0, pts=(), profiles=ALL, engine="r1", llm=False) -> Component:
    return Component(name=name, pillar=pillar, kind=kind, sign=sign, weight=weight,
                     map_points=tuple((float(x), float(y)) for x, y in pts), profiles=frozenset(profiles),
                     engine_min=engine, llm=llm)


SPREAD_MAP = ((-0.05, 0), (0.0, 40), (0.05, 65), (0.10, 80), (0.20, 100))

COMPONENTS: list[Component] = [
    # ---------------- P1 Economic moat & business quality
    _c("spread_ttm", "P1_MOAT", "map", pts=SPREAD_MAP, profiles=NONFIN),
    _c("spread_median_5y", "P1_MOAT", "map", weight=2.0, pts=SPREAD_MAP, profiles=NONFIN),
    _c("spread_trend_5y", "P1_MOAT", "map", pts=((-0.03, 0), (0.0, 50), (0.03, 100)), profiles=NONFIN),
    _c("roce_median_10y", "P1_MOAT", "pct", profiles=NONFIN),
    _c("roce_min_10y", "P1_MOAT", "pct", profiles=NONFIN),
    _c("opm_median_8y", "P1_MOAT", "pct", profiles=NONFIN),
    _c("opm_cv_8y", "P1_MOAT", "pct", sign=-1, profiles=NONFIN),
    _c("gross_margin_median_5y", "P1_MOAT", "pct", profiles=NONFIN, engine="r2"),
    _c("gm_stability_5y", "P1_MOAT", "pct", sign=-1, profiles=NONFIN, engine="r2"),
    _c("pricing_power_proxy", "P1_MOAT", "map", pts=((-0.03, 0), (0.0, 60), (0.01, 100)), profiles=NONFIN),
    _c("moat_persistence", "P1_MOAT", "map", pts=((0.0, 0), (0.5, 40), (0.8, 75), (1.0, 100)), profiles=NONFIN),
    _c("roa_ttm", "P1_MOAT", "pct", profiles=FIN),
    _c("roe_coe_spread", "P1_MOAT", "map", weight=2.0, pts=((-0.05, 0), (0.0, 40), (0.05, 70), (0.10, 100)), profiles=FIN),
    _c("nim_pct", "P1_MOAT", "pct", profiles=FIN),
    _c("cost_to_income", "P1_MOAT", "pct", sign=-1, profiles=FIN),
    _c("roe_median_5y", "P1_MOAT", "pct", profiles=FIN),
    _c("moat_grade_llm", "P1_MOAT", "map", pts=((1, 0), (5, 100)), engine="r3", llm=True),
    # ---------------- P2 Balance sheet & solvency
    _c("net_debt_ebitda", "P2_BALANCE", "map", weight=2.0,
       pts=((0.0, 100), (1.0, 85), (2.0, 65), (3.0, 45), (4.0, 25), (6.0, 0)), profiles=NONFIN),
    _c("net_debt_fcf_years", "P2_BALANCE", "map", pts=((0.0, 100), (3.0, 70), (6.0, 40), (10.0, 0)), profiles=NONFIN),
    _c("int_cover_ttm", "P2_BALANCE", "map", pts=((1.0, 0), (2.0, 30), (4.0, 60), (8.0, 85), (15.0, 100)), profiles=NONFIN),
    _c("int_cover_min_5y", "P2_BALANCE", "map", pts=((1.0, 0), (2.0, 30), (4.0, 60), (8.0, 85), (15.0, 100)), profiles=NONFIN),
    _c("altman_zpp", "P2_BALANCE", "map", pts=((1.1, 0), (2.6, 80), (5.0, 100)), profiles=NONFIN),
    _c("current_ratio", "P2_BALANCE", "map", pts=((1.0, 20), (1.5, 70), (2.0, 100)), profiles=NONFIN, engine="r2"),
    _c("cash_to_debt", "P2_BALANCE", "pct", profiles=NONFIN, engine="r2"),
    _c("st_debt_share", "P2_BALANCE", "map", pts=((0.2, 100), (0.5, 60), (0.8, 20)), profiles=NONFIN, engine="r2"),
    _c("wc_days_delta_3y", "P2_BALANCE", "pct", sign=-1, profiles=NONFIN),
    _c("de_trend_3y", "P2_BALANCE", "map", pts=((-0.2, 100), (0.0, 60), (0.3, 0)), profiles=NONFIN),
    _c("debt_equity", "P2_BALANCE", "map", pts=((0.0, 100), (0.5, 75), (1.0, 50), (2.0, 20), (3.0, 0)), profiles=NONFIN),
    _c("contingent_to_networth", "P2_BALANCE", "map", pts=((0.1, 100), (0.5, 50), (1.0, 0)), profiles=NONFIN, engine="r3"),
    _c("cet1_pct", "P2_BALANCE", "map", weight=2.0, pts=((8, 0), (10, 40), (13, 75), (16, 100)), profiles=frozenset({BANK}), engine="r2"),
    _c("gnpa_pct", "P2_BALANCE", "map", weight=2.0, pts=((1, 100), (2, 75), (4, 40), (8, 0)), profiles=FIN),
    _c("nnpa_pct", "P2_BALANCE", "map", pts=((0.5, 100), (1, 75), (2, 40), (4, 0)), profiles=FIN),
    _c("gnpa_trend_4q", "P2_BALANCE", "map", pts=((-1.0, 100), (0.0, 60), (1.0, 20), (2.0, 0)), profiles=FIN),
    _c("provision_coverage", "P2_BALANCE", "pct", profiles=FIN, engine="r2"),
    _c("deposit_vs_advance_growth", "P2_BALANCE", "pct", profiles=frozenset({BANK})),
    _c("fin_leverage", "P2_BALANCE", "map", weight=2.0, pts=((4.0, 100), (7.0, 50), (10.0, 0)), profiles=frozenset({NBFC_FIN})),
    _c("borrowing_cost", "P2_BALANCE", "pct", sign=-1, profiles=frozenset({NBFC_FIN})),
    # ---------------- P3 Earnings quality & forensics
    _c("cfo_to_pat_5y", "P3_EARNINGS", "map", weight=2.0, pts=((0.5, 0), (0.8, 50), (1.0, 80), (1.2, 100)), profiles=NONFIN),
    _c("fcf_conversion_5y", "P3_EARNINGS", "map", pts=((0.0, 0), (0.4, 40), (0.7, 75), (1.0, 100)), profiles=NONFIN),
    _c("cfo_to_ebitda_5y", "P3_EARNINGS", "pct", profiles=NONFIN),
    _c("accrual_ratio_sloan_abs", "P3_EARNINGS", "map", weight=2.0, pts=((0.02, 100), (0.05, 60), (0.10, 20), (0.15, 0)), profiles=NONFIN),
    _c("accrual_ratio_bs_abs", "P3_EARNINGS", "map", pts=((0.02, 100), (0.05, 60), (0.10, 20), (0.15, 0)), profiles=NONFIN, engine="r2"),
    _c("beneish_level", "P3_EARNINGS", "map", weight=2.0, pts=((0, 0), (50, 50), (100, 100)), profiles=NONFIN),
    _c("other_income_share", "P3_EARNINGS", "map", pts=((0.10, 100), (0.25, 50), (0.50, 0))),
    _c("cash_tax_gap", "P3_EARNINGS", "map", pts=((0.0, 100), (0.05, 80), (0.10, 40), (0.20, 0))),
    _c("capitalisation_proxy", "P3_EARNINGS", "pct", sign=-1, profiles=NONFIN),
    _c("receivable_days_delta_3y", "P3_EARNINGS", "map", pts=((-10, 100), (0, 70), (20, 30), (40, 0)), profiles=NONFIN),
    _c("inventory_days_delta_3y", "P3_EARNINGS", "map", pts=((-10, 100), (0, 70), (20, 30), (40, 0)), profiles=NONFIN),
    _c("payable_days_delta_3y", "P3_EARNINGS", "map", pts=((-10, 100), (0, 70), (20, 30), (40, 0)), profiles=NONFIN),
    _c("depreciation_rate_cv_5y", "P3_EARNINGS", "pct", sign=-1, profiles=NONFIN),
    _c("reserves_leakage_5y", "P3_EARNINGS", "map", pts=((0.05, 100), (0.15, 50), (0.30, 0)), profiles=NONFIN),
    _c("audit_opinion_clean", "P3_EARNINGS", "binary", engine="r2"),
    _c("credit_cost", "P3_EARNINGS", "pct", sign=-1, profiles=FIN, engine="r2"),
    _c("gnpa_delta_4q_neg", "P3_EARNINGS", "map", pts=((-1.0, 100), (0.0, 60), (1.0, 20), (2.0, 0)), profiles=FIN),
    # ---------------- P4 Growth & reinvestment runway
    _c("reinvestment_rate_5y", "P4_GROWTH", "map", pts=((0.0, 40), (0.4, 100), (0.8, 100), (1.2, 40), (2.0, 20)), profiles=NONFIN),
    _c("incremental_roic_5y", "P4_GROWTH", "map", weight=2.0, pts=((0.0, 0), (0.10, 40), (0.20, 75), (0.30, 100)), profiles=NONFIN),
    _c("fundamental_growth", "P4_GROWTH", "pct", profiles=NONFIN),
    _c("growth_gap", "P4_GROWTH", "map", pts=((-0.05, 100), (0.0, 60), (0.05, 30), (0.10, 0)), profiles=NONFIN),
    _c("sales_cagr_3y", "P4_GROWTH", "pct"),
    _c("sales_cagr_5y", "P4_GROWTH", "pct"),
    _c("pat_cagr_5y", "P4_GROWTH", "pct"),
    _c("eps_cagr_5y", "P4_GROWTH", "pct"),
    _c("growth_consistency_5y", "P4_GROWTH", "map", pts=((0.4, 20), (0.8, 70), (1.0, 100))),
    _c("sales_yoy_ttm", "P4_GROWTH", "pct"),
    _c("pat_yoy_ttm", "P4_GROWTH", "pct"),
    _c("bvps_cagr_5y", "P4_GROWTH", "pct", profiles=FIN),
    _c("ppop_growth_3y", "P4_GROWTH", "pct", profiles=FIN),
    _c("tam_headroom_llm", "P4_GROWTH", "map", pts=((1, 0), (5, 100)), engine="r3", llm=True),
    # ---------------- P5 Management & capital allocation
    _c("capex_return_test", "P5_MANAGEMENT", "map", pts=((0.0, 0), (0.1, 40), (0.2, 70), (0.3, 100)), profiles=NONFIN),
    _c("self_funding_5y", "P5_MANAGEMENT", "map", pts=((0.0, 20), (0.6, 60), (1.0, 100)), profiles=NONFIN),
    _c("dilution_5y", "P5_MANAGEMENT", "map", pts=((-0.02, 100), (0.0, 70), (0.05, 0))),
    _c("payout_discipline", "P5_MANAGEMENT", "map", pts=((0, 0), (50, 50), (100, 100))),
    _c("promoter_pct", "P5_MANAGEMENT", "map", pts=((10, 20), (20, 40), (35, 70), (50, 100))),
    _c("promoter_chg_1y", "P5_MANAGEMENT", "map", pts=((-5, 0), (-2, 40), (0, 70), (2, 100))),
    _c("promoter_chg_3y", "P5_MANAGEMENT", "map", pts=((-10, 0), (-3, 40), (0, 70), (3, 100))),
    _c("pledged_pct_of_promoter", "P5_MANAGEMENT", "map", weight=2.0, pts=((0, 100), (10, 80), (25, 50), (50, 20), (60, 0))),
    _c("pledge_delta_4q", "P5_MANAGEMENT", "map", pts=((-5, 100), (0, 70), (5, 30), (10, 0))),
    _c("insider_net_buy_12m", "P5_MANAGEMENT", "map", pts=((-0.005, 20), (0.0, 60), (0.005, 100))),
    _c("inst_chg_1y", "P5_MANAGEMENT", "pct"),
    _c("rating_migration_12m", "P5_MANAGEMENT", "map", pts=((-3, 0), (-1, 30), (0, 70), (1, 100))),
    _c("adverse_events_90d_clean", "P5_MANAGEMENT", "binary"),
    _c("mgmt_grade_llm", "P5_MANAGEMENT", "map", pts=((1, 0), (5, 100)), engine="r3", llm=True),
    # ---------------- P6 Valuation & margin of safety
    _c("pe_band_pos_10y", "P6_VALUATION", "map", pts=((0.0, 100), (0.5, 50), (1.0, 0))),
    _c("ev_ebitda_band_pos", "P6_VALUATION", "map", pts=((0.0, 100), (0.5, 50), (1.0, 0)), profiles=NONFIN),
    _c("earnings_yield", "P6_VALUATION", "pct"),
    _c("fcf_yield", "P6_VALUATION", "pct", profiles=NONFIN),
    _c("div_yield", "P6_VALUATION", "pct"),
    _c("growth_gap_val", "P6_VALUATION", "map", pts=((-0.05, 100), (0.0, 60), (0.05, 30), (0.10, 0)), profiles=NONFIN),
    _c("mos_base", "P6_VALUATION", "map", weight=2.0, pts=((-0.40, 0), (-0.20, 20), (0.0, 50), (0.20, 75), (0.50, 100))),
    _c("pb_vs_justified", "P6_VALUATION", "map", pts=((0.5, 100), (1.0, 50), (1.5, 20), (2.0, 0)), profiles=FIN),
]

COMPONENT_BY_NAME = {c.name: c for c in COMPONENTS}
assert len(COMPONENT_BY_NAME) == len(COMPONENTS), "duplicate component names"


def applicable(profile: str, engine: str, variant: str) -> list[Component]:
    return [c for c in COMPONENTS if c.applies(profile, engine, variant)]


def map_score(x: float, pts: tuple[tuple[float, float], ...]) -> float:
    """Piecewise-linear interpolation, clipped to the end points."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return float(np.interp(x, xs, ys))


def component_scores(raw: pd.DataFrame, groups: pd.Series, profile_of: pd.Series, engine: str, variant: str,
                     min_group: int = 8) -> tuple[pd.DataFrame, dict[str, dict[str, float]]]:
    """Cross-sectional scoring of every component for every symbol.

    raw: DataFrame index=symbol, columns=metric names (NaN = UNKNOWN / NA).
    groups: Series symbol -> percentile group (profile). profile_of: symbol -> profile.
    Returns DataFrame index=symbol with one column per component holding the 0..100 score
    (NaN when the component does not apply or is unknown) and the priors dict
    (component -> {profile: prior score, "__universe__": prior}). Frames carry NO attrs: pandas
    deep-copies attrs on every column access, which made a 1,200-name run take minutes."""
    from ..fundamentals.base import percentile_grouped
    raw = raw.copy(deep=False); raw.attrs = {}
    out = pd.DataFrame(index=raw.index, dtype=float)
    applies_cache: dict[str, bool] = {}
    priors: dict[str, dict[str, float]] = {}
    for c in COMPONENTS:
        col = c.name
        if col not in raw.columns:
            out[col] = np.nan
            priors[col] = {}
            continue
        s = raw[col].astype(float)
        mask_applies = profile_of.map(lambda p: c.applies(p, engine, variant)).astype(bool).reindex(raw.index).fillna(False)
        s = s.where(mask_applies)
        if c.kind == "pct":
            sc = percentile_grouped(s * c.sign, groups, min_group=min_group)
        elif c.kind == "map":
            sc = s.map(lambda v: np.nan if pd.isna(v) else map_score(float(v), c.map_points))
        else:                                                   # binary: 1 -> 100, 0 -> 0
            sc = s.map(lambda v: np.nan if pd.isna(v) else (100.0 if float(v) >= 0.5 else 0.0))
        sc = sc.where(mask_applies)
        out[col] = sc
        # prior per group = median score of names that know it; universe fallback
        pri: dict[str, float] = {}
        known = sc.dropna()
        if len(known):
            uni = float(known.median())
            for g, idx in groups.groupby(groups).groups.items():
                k = known.reindex(idx).dropna()
                pri[str(g)] = float(k.median()) if len(k) >= min_group else uni
            pri["__universe__"] = uni
        priors[col] = pri
    return out, priors


def pillar_scores_for(symbol: str, scores: pd.DataFrame, raw: pd.DataFrame, profile: str, engine: str,
                      variant: str, priors: Optional[dict] = None, min_known_share: float = 0.5,
                      default_prior: float = 50.0, score_row: Optional[dict] = None,
                      raw_row: Optional[dict] = None) -> dict[str, PillarScore]:
    """Assemble the six PillarScore objects for one symbol from the cross-sectional score frame
    (pass `score_row`/`raw_row` dicts to avoid per-cell frame access in a universe loop)."""
    priors = priors or {}
    score_row = score_row if score_row is not None else scores.loc[symbol].to_dict()
    raw_row = raw_row if raw_row is not None else raw.loc[symbol].to_dict()
    comps = applicable(profile, engine, variant)
    pillars: dict[str, PillarScore] = {}
    for pname in PILLARS:
        cs: list[ComponentScore] = []
        w_known = w_total = 0.0
        num = 0.0
        for c in comps:
            if c.pillar != pname:
                continue
            sc = score_row.get(c.name, np.nan)
            rv = raw_row.get(c.name, np.nan)
            sc = np.nan if sc is None else sc
            rv = np.nan if rv is None else rv
            pri = priors.get(c.name, {})
            prior = pri.get(profile, pri.get("__universe__", default_prior)) if pri else default_prior
            w_total += c.weight
            if pd.notna(sc):
                w_known += c.weight
                num += c.weight * float(sc)
                cs.append(ComponentScore(c.name, None if pd.isna(rv) else float(rv), float(sc), OK, c.weight,
                                         provenance="fund_metrics", shrunk_to_prior=False, prior=prior))
            else:
                num += c.weight * prior
                cs.append(ComponentScore(c.name, None, prior, UNKNOWN, c.weight, provenance="prior",
                                         shrunk_to_prior=True, prior=prior))
        if w_total == 0:
            pillars[pname] = PillarScore(pname, None, NA, 0.0, 0.0, cs)
            continue
        score = num / w_total
        status = OK if w_known / w_total >= min_known_share else UNKNOWN
        if status == UNKNOWN:
            # pillar prior = weighted mean of component priors (what a name that knows nothing would get)
            score = sum(c.weight * (c.prior if c.prior is not None else default_prior) for c in cs) / w_total
        pillars[pname] = PillarScore(pname, float(score), status, w_known, w_total, cs)
    return pillars


def composite(pillars: dict[str, PillarScore], weights: dict[str, float]) -> Optional[float]:
    """Weighted mean over ALL six pillars (UNKNOWN pillars carry their prior); None only when
    every pillar is NA (cannot happen for a mapped profile)."""
    num = den = 0.0
    for k, w in weights.items():
        p = pillars.get(k)
        if p is None or p.score is None:
            continue
        num += w * p.score
        den += w
    return None if den == 0 else float(num / den)
