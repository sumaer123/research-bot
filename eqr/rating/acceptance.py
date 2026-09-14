"""Pre-registered acceptance bar for the rating engine (methodology plan §6.2).

Every check must hold for VALIDATED. Changing any threshold after a run is a new trial
and must be ledgered (eqr/validate/trials.py) like a sleeve grid change."""
from __future__ import annotations

BAR = {
    "decile_monotonic_overall": True,          # mean 12m excess strictly increasing over score deciles
    "decile_monotonic_years_min_share": 0.70,  # share of test years with monotonic deciles
    "tiers_ordered": True,                     # CONVICTION_BUY > SPECULATIVE_BUY > HOLD > TRIM > SELL on mean excess
    "long_short_min_pp": 0.06,                 # BUY tiers minus SELL/TRIM tiers, per year
    "long_short_t_min": 2.0,                   # Newey-West (lag 11)
    "ic_mean_min": 0.05,                       # mean rank IC of score vs 12m excess
    "ic_t_min": 2.0,
    "mos_ic_min": 0.03,                        # MoS vs 36m excess
    "mos_ic_t_min": 1.5,
    "hit_conviction_buy_min": 0.60,
    "hit_all_buy_min": 0.55,
    "hit_sell_min": 0.55,                      # share of SELL-tier names with excess < 0
    "hard_flag_precision_min": 0.65,           # historically computable HARD flags only
    "brier_max": 0.24,
    "brier_vs_climatology_min_gain": 0.01,
    "coverage_neutral_abs_corr_max": 0.10,     # |corr(score, coverage)|
    "dci_informative": True,                   # IC(HIGH-DCI cohort) >= IC(LOW-DCI cohort)
    "sector_max_share_conviction": 0.40,       # no profile > 40% of CONVICTION_BUY names on average
    "sector_ls_positive_min_profiles": 3,      # long-short positive within >= 3 of 6 profiles
    "monthly_transition_max": 0.25,
    "min_tier_share": 0.05,                    # no verdict below 5% of the universe on average
    "dsr_p_max": 0.05,
    "holdout_long_short_positive": True,
}

# checks that cannot be evaluated on r1 (forward-only inputs) are reported as NOT_EVALUABLE, never as passes
NOT_EVALUABLE_R1: tuple[str, ...] = ()


def evaluate(metrics: dict) -> dict:
    """metrics -> {check: {"value", "threshold", "pass" | None}} plus 'verdict'."""
    m = metrics
    out: dict = {}

    def chk(name, value, ok, threshold):
        out[name] = {"value": value, "threshold": threshold, "pass": (None if ok is None else bool(ok))}

    chk("decile_monotonic_overall", m.get("decile_monotonic_overall"), m.get("decile_monotonic_overall"), True)
    v = m.get("decile_monotonic_years_share"); chk("decile_monotonic_years_min_share", v, None if v is None else v >= BAR["decile_monotonic_years_min_share"], BAR["decile_monotonic_years_min_share"])
    chk("tiers_ordered", m.get("tiers_ordered"), m.get("tiers_ordered"), True)
    v = m.get("long_short_pp"); chk("long_short_min_pp", v, None if v is None else v >= BAR["long_short_min_pp"], BAR["long_short_min_pp"])
    v = m.get("long_short_t"); chk("long_short_t_min", v, None if v is None else v >= BAR["long_short_t_min"], BAR["long_short_t_min"])
    v = m.get("ic_mean"); chk("ic_mean_min", v, None if v is None else v >= BAR["ic_mean_min"], BAR["ic_mean_min"])
    v = m.get("ic_t"); chk("ic_t_min", v, None if v is None else v >= BAR["ic_t_min"], BAR["ic_t_min"])
    v = m.get("mos_ic_mean"); chk("mos_ic_min", v, None if v is None else v >= BAR["mos_ic_min"], BAR["mos_ic_min"])
    v = m.get("mos_ic_t"); chk("mos_ic_t_min", v, None if v is None else v >= BAR["mos_ic_t_min"], BAR["mos_ic_t_min"])
    v = m.get("hit_conviction_buy"); chk("hit_conviction_buy_min", v, None if v is None else v >= BAR["hit_conviction_buy_min"], BAR["hit_conviction_buy_min"])
    v = m.get("hit_all_buy"); chk("hit_all_buy_min", v, None if v is None else v >= BAR["hit_all_buy_min"], BAR["hit_all_buy_min"])
    v = m.get("hit_sell"); chk("hit_sell_min", v, None if v is None else v >= BAR["hit_sell_min"], BAR["hit_sell_min"])
    v = m.get("hard_flag_precision"); chk("hard_flag_precision_min", v, None if v is None else v >= BAR["hard_flag_precision_min"], BAR["hard_flag_precision_min"])
    v = m.get("brier"); chk("brier_max", v, None if v is None else v <= BAR["brier_max"], BAR["brier_max"])
    v = m.get("brier_gain_vs_climatology"); chk("brier_vs_climatology_min_gain", v, None if v is None else v >= BAR["brier_vs_climatology_min_gain"], BAR["brier_vs_climatology_min_gain"])
    v = m.get("score_coverage_corr"); chk("coverage_neutral_abs_corr_max", v, None if v is None else abs(v) <= BAR["coverage_neutral_abs_corr_max"], BAR["coverage_neutral_abs_corr_max"])
    chk("dci_informative", m.get("dci_informative"), m.get("dci_informative"), True)
    v = m.get("sector_max_share_conviction"); chk("sector_max_share_conviction", v, None if v is None else v <= BAR["sector_max_share_conviction"], BAR["sector_max_share_conviction"])
    v = m.get("sector_ls_positive_profiles"); chk("sector_ls_positive_min_profiles", v, None if v is None else v >= BAR["sector_ls_positive_min_profiles"], BAR["sector_ls_positive_min_profiles"])
    v = m.get("monthly_transition"); chk("monthly_transition_max", v, None if v is None else v <= BAR["monthly_transition_max"], BAR["monthly_transition_max"])
    v = m.get("min_tier_share"); chk("min_tier_share", v, None if v is None else v >= BAR["min_tier_share"], BAR["min_tier_share"])
    v = m.get("dsr_p"); chk("dsr_p_max", v, None if v is None else v <= BAR["dsr_p_max"], BAR["dsr_p_max"])
    chk("holdout_long_short_positive", m.get("holdout_long_short"), None if m.get("holdout_long_short") is None else m["holdout_long_short"] > 0, True)
    passes = [c["pass"] for c in out.values()]
    verdict = "VALIDATED" if all(p is True for p in passes) else "NOT VALIDATED"
    out["verdict"] = verdict
    out["n_pass"] = sum(1 for p in passes if p is True)
    out["n_fail"] = sum(1 for p in passes if p is False)
    out["n_not_evaluable"] = sum(1 for p in passes if p is None)
    return out
