"""Decision matrix (methodology plan §4.1) — ordered rules, first match wins."""
from __future__ import annotations

from typing import Optional

from .model import Decision, RedFlag, Confidence, VERDICT_ORDER


def decide(
    S: float | None,
    mos: float | None,
    dci_band: str,
    flags: list[RedFlag],
    growth_catalyst: bool,
    p2: float | None
) -> Decision:
    """Apply the decision rules R1–R9 and R5B.

    Args:
        S: score (0..100), None → NO_RATING
        mos: margin of safety (fraction, e.g. 0.20 = +20%), None = unknown
        dci_band: 'HIGH', 'MED', 'LOW', 'NONE'
        flags: list of RedFlag objects
        growth_catalyst: deterministic catalyst test result
        p2: Pillar 2 (balance sheet) score

    Returns:
        Decision with verdict, rule_id, and reason.
    """
    if S is None or dci_band == "NONE":
        return Decision("NO_RATING", "NO_RATING", "DATA_ERROR / insufficient coverage", "LOW")

    hard = [f for f in flags if f.tier == "HARD"]
    soft = [f for f in flags if f.tier == "SOFT"]
    watch = [f for f in flags if f.tier == "WATCH"]

    # R1: HARD flag → SELL with HIGH conviction
    if hard:
        return Decision("SELL", "R1_HARD_FLAG", f"hard flag: {hard[0].code}", "HIGH")

    # R2: S < 35 → SELL
    if S < 35:
        return Decision("SELL", "R2_SCORE_LT_35", f"score {S:.0f} < 35", "MED")

    # R3: MoS ≤ −25% → TRIM (price beats quality)
    if mos is not None and mos <= -0.25:
        return Decision("TRIM", "R3_OVERVALUED_25", f"overvalued: MoS {mos:.1%} ≤ -25%", "MED")

    # R4: 35 ≤ S < 50 → TRIM
    if 35 <= S < 50:
        return Decision("TRIM", "R4_SCORE_35_49", f"score {S:.0f} in 35-49 range", "MED")

    # R5: S ≥ 80, MoS ≥ 20%, no soft, no watch, DCI HIGH → CONVICTION_BUY
    if (S >= 80 and mos is not None and mos >= 0.20 and
        not soft and not watch and dci_band == "HIGH"):
        return Decision("CONVICTION_BUY", "R5_CONVICTION",
                       f"score {S:.0f}, MoS {mos:.1%}, high conviction", "HIGH")

    # R5B: S ≥ 80, MoS ≥ 20%, no soft, ≤ 1 watch, DCI in (HIGH, MED) → SPECULATIVE_BUY
    if (S >= 80 and mos is not None and mos >= 0.20 and
        not soft and len(watch) <= 1 and dci_band in ("HIGH", "MED")):
        return Decision("SPECULATIVE_BUY", "R5B_CONVICTION_DATA_OR_WATCH_LIMITED",
                       f"score {S:.0f}, MoS {mos:.1%}, data or watch limit", "MED")

    # R6: S ≥ 70, growth_catalyst, P2 ≥ 40, no soft, ≤ 1 watch, DCI in (HIGH, MED), MoS > −10% → SPECULATIVE_BUY
    if (S >= 70 and growth_catalyst and (p2 is None or p2 >= 40) and
        not soft and len(watch) <= 1 and dci_band in ("HIGH", "MED") and
        (mos is None or mos > -0.10)):
        return Decision("SPECULATIVE_BUY", "R6_SPECULATIVE",
                       f"score {S:.0f}, growth catalyst, P2 {p2}, MoS {mos}", "MED")

    # R7: S ≥ 80, MoS in [−10%, 20%) → HOLD (quality but wait for price)
    if S >= 80 and (mos is None or (-0.10 <= mos < 0.20)):
        return Decision("HOLD", "R7_QUALITY_WAIT_FOR_PRICE",
                       f"score {S:.0f}, quality but MoS {mos}", "MED")

    # R8: 50 ≤ S < 70 OR |MoS| ≤ 10% → HOLD
    if 50 <= S < 70 or (mos is not None and abs(mos) <= 0.10):
        return Decision("HOLD", "R8_HOLD_BAND",
                       f"score {S:.0f} or MoS {mos} in hold band", "MED")

    # R9: everything else (S ≥ 70 with no catalyst) → HOLD
    return Decision("HOLD", "R9_GOOD_BUT_NO_CATALYST",
                   f"score {S:.0f} but no catalyst", "MED")


def apply_caps(decision: Decision, flags: list[RedFlag]) -> Decision:
    """Apply soft-flag caps: min(verdict, cap(f)) over SOFT flags.

    HARD flags cap at SELL (applied earlier in decide()). SOFT flags cap at HOLD or TRIM.
    WATCH flags have no cap.
    """
    from .flags import most_restrictive_cap

    soft = [f for f in flags if f.tier == "SOFT"]
    if not soft:
        return decision

    cap = most_restrictive_cap(soft)
    if cap is None:
        return decision

    # Compare verdict to cap using VERDICT_ORDER
    verdict_rank = VERDICT_ORDER.get(decision.verdict, 999)
    cap_rank = VERDICT_ORDER.get(cap, 999)

    if verdict_rank > cap_rank:
        # Verdict is "higher" (better) than cap; downgrade to cap
        return Decision(
            cap, decision.rule_id, decision.reason,
            decision.conviction, False, cap, decision.verdict
        )

    return decision


def apply_confidence(decision: Decision, band: str) -> Decision:
    """Adjust conviction and verdict based on DCI band.

    - MED band: CONVICTION_BUY → SPECULATIVE_BUY; conviction MED for BUY types
    - LOW band: any BUY down one step (CONVICTION→SPECULATIVE, SPECULATIVE→HOLD)
               SELL-by-score gets reason suffix '(low data)'
    - NONE → NO_RATING
    - HARD-flag SELL is never softened
    """
    if band == "NONE":
        return Decision("NO_RATING", "CONFIDENCE_NONE", "insufficient data", "LOW")

    if decision.verdict == "SELL" and decision.rule_id == "R1_HARD_FLAG":
        # HARD-flag SELL never softened
        return decision

    if band == "MED":
        if decision.verdict == "CONVICTION_BUY":
            return Decision("SPECULATIVE_BUY", decision.rule_id, decision.reason,
                          "MED", True, decision.capped_by, decision.verdict_before_caps)
        # BUY types in MED data: conviction drops to MED
        if decision.verdict in ("SPECULATIVE_BUY", "HOLD"):
            return Decision(decision.verdict, decision.rule_id, decision.reason,
                          "MED", False, decision.capped_by, decision.verdict_before_caps)

    elif band == "LOW":
        if decision.verdict == "CONVICTION_BUY":
            return Decision("SPECULATIVE_BUY", decision.rule_id, decision.reason,
                          "LOW", True, decision.capped_by, decision.verdict_before_caps)
        elif decision.verdict == "SPECULATIVE_BUY":
            return Decision("HOLD", decision.rule_id, decision.reason,
                          "LOW", True, decision.capped_by, decision.verdict_before_caps)
        elif decision.verdict == "SELL" and decision.rule_id != "R1_HARD_FLAG":
            # SELL-by-score gets reason suffix
            reason = decision.reason + " (low data)" if "(low data)" not in decision.reason else decision.reason
            return Decision("SELL", decision.rule_id, reason,
                          "LOW", True, decision.capped_by, decision.verdict_before_caps)
        # HOLD/TRIM unchanged in conviction but marked downgraded
        return Decision(decision.verdict, decision.rule_id, decision.reason,
                      "LOW", False, decision.capped_by, decision.verdict_before_caps)

    return decision


def hysteresis(prev_verdict: str | None, new: Decision, S: float | None, mos: float | None) -> Decision:
    """Apply hysteresis to prevent churn: upgrades need margin, downgrades immediate.

    An UPGRADE (better verdict) only sticks when the rule threshold is exceeded by:
    - S ≥ rule threshold + 2
    - MoS ≥ threshold + 3 pp (where rule has MoS condition)

    Otherwise keep prev_verdict with hysteresis_applied=True and rule_id suffixed '+HYST'.
    Downgrades apply immediately.
    """
    if prev_verdict is None:
        # First rating; no hysteresis
        return new

    prev_rank = VERDICT_ORDER.get(prev_verdict, 2)
    new_rank = VERDICT_ORDER.get(new.verdict, 2)

    if new_rank > prev_rank:
        # Upgrade: check margin
        # Extract S threshold from rule_id
        threshold_S = None
        if "R5" in new.rule_id:
            threshold_S = 80
        elif "R6" in new.rule_id:
            threshold_S = 70
        elif "R7" in new.rule_id:
            threshold_S = 80
        elif "R8" in new.rule_id:
            threshold_S = 50
        elif "R4" in new.rule_id:
            threshold_S = 35

        # Check if we meet the upgrade criteria
        upgrade_ok = True
        if threshold_S is not None and S is not None:
            if S < threshold_S + 2:
                upgrade_ok = False

        # Check MoS margin (rules with MoS ≥ 20% threshold)
        if "R5" in new.rule_id and mos is not None:
            if mos < 0.20 + 0.03:  # 20% + 3 pp
                upgrade_ok = False

        if not upgrade_ok:
            # Don't upgrade; keep previous verdict
            return Decision(
                prev_verdict, new.rule_id + "+HYST", new.reason,
                new.conviction, new.downgraded_by_confidence,
                new.capped_by, new.verdict_before_caps,
                hysteresis_applied=True
            )

    # Downgrade or no change: apply immediately
    return new


def growth_catalyst(
    metrics: dict[str, float | None],
    p4: float | None
) -> bool:
    """Deterministic growth catalyst test per methodology plan §4.1.

    P4 ≥ 70 AND (
        fundamental_growth ≥ 12% with growth_gap ≤ 0
        OR pat_yoy_ttm ≥ 20% with sales_yoy_ttm ≥ 10%
        OR eps_cagr_5y ≥ 15% with growth_consistency_5y ≥ 0.8
    )

    Returns:
        True if catalyst is triggered, False otherwise.
    """
    if p4 is None or p4 < 70:
        return False

    fundamental_growth = metrics.get("fundamental_growth")
    growth_gap = metrics.get("growth_gap")
    pat_yoy = metrics.get("pat_yoy_ttm")
    sales_yoy = metrics.get("sales_yoy_ttm")
    eps_cagr = metrics.get("eps_cagr_5y")
    growth_consistency = metrics.get("growth_consistency_5y")

    # Test 1: fundamental_growth ≥ 12% with growth_gap ≤ 0
    if fundamental_growth is not None and growth_gap is not None:
        if fundamental_growth >= 0.12 and growth_gap <= 0.0:
            return True

    # Test 2: pat_yoy_ttm ≥ 20% with sales_yoy_ttm ≥ 10%
    if pat_yoy is not None and sales_yoy is not None:
        if pat_yoy >= 0.20 and sales_yoy >= 0.10:
            return True

    # Test 3: eps_cagr_5y ≥ 15% with growth_consistency_5y ≥ 0.8
    if eps_cagr is not None and growth_consistency is not None:
        if eps_cagr >= 0.15 and growth_consistency >= 0.8:
            return True

    return False


def decide_full(
    S: float | None,
    mos: float | None,
    conf: Confidence,
    flags: list[RedFlag],
    metrics: dict[str, float | None],
    p2: float | None,
    p4: float | None,
    prev_verdict: str | None = None
) -> Decision:
    """Chain the decision pipeline: decide → apply_caps → apply_confidence → hysteresis.

    Returns:
        Decision with full context (verdict, conviction, caps, hysteresis, etc.).
    """
    # Compute catalyst
    catalyst = growth_catalyst(metrics, p4)

    # Step 1: decide (rules R1–R9, R5B)
    decision = decide(S, mos, conf.band, flags, catalyst, p2)

    # Step 2: apply SOFT-flag caps
    decision = apply_caps(decision, flags)

    # Step 3: apply confidence downgrade
    decision = apply_confidence(decision, conf.band)

    # Step 4: hysteresis
    decision = hysteresis(prev_verdict, decision, S, mos)

    return decision
