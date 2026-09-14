"""Red-Flag Override Engine (methodology plan §3.3).

Three tiers: HARD (cap = SELL), SOFT (cap = HOLD or TRIM), WATCH (no cap).
Availability: 'hist' = computable over 2017→ (calibratable), 'fwd' = forward-only.
A flag whose inputs are UNKNOWN/absent is NOT fired and NOT 'clean' — return nothing for it.
"""
from __future__ import annotations

from typing import Optional

from .model import RedFlag


FLAG_CATALOGUE: dict[str, dict] = {
    # HARD flags (cap = SELL)
    "FORENSIC_BENEISH_2Y": {
        "tier": "HARD", "cap": "SELL", "availability": "hist",
        "description": "Beneish M > −1.78 in last 2 FYs AND accrual_ratio_sloan > 10% in latest FY"
    },
    "FORENSIC_CASH_DIVERGENCE": {
        "tier": "HARD", "cap": "SELL", "availability": "hist",
        "description": "accrual_ratio_sloan > 15% in each of last 2 FYs AND cfo_to_pat_5y < 0.5 (non-fin)"
    },
    "SOLVENCY_BREACH": {
        "tier": "HARD", "cap": "SELL", "availability": "hist",
        "description": "non-fin: Altman Z'' < 1.1 AND int_cover_ttm < 1.5; or net_debt_ebitda > 6 AND int_cover < 1.0"
    },
    "CAPITAL_BREACH_BANK": {
        "tier": "HARD", "cap": "SELL", "availability": "hist/fwd",
        "description": "GNPA % > 10% (hist) or CET1 < 8% (fwd)"
    },
    "AUDIT_QUALIFIED_OR_RESIGNED": {
        "tier": "HARD", "cap": "SELL", "availability": "fwd",
        "description": "modified/adverse/disclaimer opinion in latest FY, or auditor resignation ≤ 12 months"
    },
    "DEFAULT_EVENT": {
        "tier": "HARD", "cap": "SELL", "availability": "fwd",
        "description": "credit rating D / default announcement ≤ 90 days"
    },
    "PLEDGE_GT_50": {
        "tier": "HARD", "cap": "SELL", "availability": "fwd",
        "description": "pledged % of promoter holding > 50"
    },
    "GSM": {
        "tier": "HARD", "cap": "SELL", "availability": "fwd",
        "description": "on the GSM list on as_of"
    },
    "REGULATORY_FRAUD": {
        "tier": "HARD", "cap": "SELL", "availability": "fwd",
        "description": "SEBI order naming company/promoter for fraud, or forensic audit announced ≤ 180 days"
    },
    # SOFT flags (cap = HOLD or TRIM)
    "BENEISH_1Y": {
        "tier": "SOFT", "cap": "HOLD", "availability": "hist",
        "description": "M > −1.78 in latest FY only"
    },
    "STALE_STATEMENTS": {
        "tier": "SOFT", "cap": "HOLD", "availability": "hist",
        "description": "latest statement > 200 days old (> 400 days → NO_RATING)"
    },
    "PROMOTER_SELLING": {
        "tier": "SOFT", "cap": "HOLD", "availability": "hist/fwd",
        "description": "promoter_chg_1y ≤ −5 pp and no ofs_matched bulk/block deal"
    },
    "MOAT_EROSION": {
        "tier": "SOFT", "cap": "HOLD", "availability": "hist",
        "description": "spread_ttm < 0 after spread_median_5y > 5%, or OPM down > 500 bp over 3y with sales growing"
    },
    "DEBT_SPIKE": {
        "tier": "SOFT", "cap": "HOLD", "availability": "hist",
        "description": "net_debt_ebitda rose by > 2.0 turns in 12m"
    },
    "OTHER_INCOME_DEPENDENCE": {
        "tier": "SOFT", "cap": "HOLD", "availability": "hist",
        "description": "other_income_share > 50% for 2 FYs"
    },
    "LEVERAGED_BUYBACK": {
        "tier": "SOFT", "cap": "TRIM", "availability": "hist",
        "description": "buyback while net_debt_ebitda > 3"
    },
    "PLEDGE_GT_25": {
        "tier": "SOFT", "cap": "TRIM", "availability": "fwd",
        "description": "pledged 25–50%"
    },
    "ASM_STAGE_2_PLUS": {
        "tier": "SOFT", "cap": "HOLD", "availability": "fwd",
        "description": "surveillance stage 2+ on as_of"
    },
    "FO_BAN": {
        "tier": "SOFT", "cap": "HOLD", "availability": "fwd",
        "description": "FO ban on as_of"
    },
    "RATING_DOWNGRADE_2N": {
        "tier": "SOFT", "cap": "HOLD", "availability": "fwd",
        "description": "≥ 2 notches down in 12m, or outlook negative with notch ≤ BBB"
    },
    "PHARMA_USFDA_OAI": {
        "tier": "SOFT", "cap": "HOLD", "availability": "fwd",
        "description": "warning letter / OAI / import alert ≤ 12 months (PHARMA profile)"
    },
    # WATCH flags (no cap; blocks Conviction BUY)
    "OTHER_INCOME_25_50": {
        "tier": "WATCH", "cap": None, "availability": "hist",
        "description": "other_income_share 25–50%"
    },
    "PLEDGE_10_25": {
        "tier": "WATCH", "cap": None, "availability": "fwd",
        "description": "pledged 10–25%"
    },
    "PROMOTER_SELLING_2_5PP": {
        "tier": "WATCH", "cap": None, "availability": "hist",
        "description": "promoter_chg_1y −2 to −5 pp"
    },
    "BENEISH_WATCH": {
        "tier": "WATCH", "cap": None, "availability": "hist",
        "description": "Beneish M −2.22 to −1.78"
    },
    "WC_DAYS_UP_20": {
        "tier": "WATCH", "cap": None, "availability": "hist",
        "description": "working-capital days +20 in 3y"
    },
    "TAX_GAP": {
        "tier": "WATCH", "cap": None, "availability": "hist",
        "description": "cash tax rate gap > 10 pp for 3 FYs"
    },
    "VALUATION_DISPERSION_GT_50": {
        "tier": "WATCH", "cap": None, "availability": "hist",
        "description": "valuation model dispersion > 50%"
    },
    "DEBT_UP_1_TURN": {
        "tier": "WATCH", "cap": None, "availability": "hist",
        "description": "net_debt_ebitda up 1 turn in 12m"
    },
}


def most_restrictive_cap(flags: list[RedFlag]) -> str | None:
    """Return the most restrictive cap from the list of flags using VERDICT_ORDER.
    HARD -> SELL (0), SOFT -> HOLD/TRIM (1-2), WATCH -> None.
    Return the smallest cap value by VERDICT_ORDER, or None if no cap applies."""
    from .model import VERDICT_ORDER

    caps = [f.cap for f in flags if f.cap is not None]
    if not caps:
        return None
    # Order by VERDICT_ORDER: SELL=0, TRIM=1, HOLD=2
    return min(caps, key=lambda c: VERDICT_ORDER.get(c, 999))


def evaluate_flags(
    metrics: dict[str, float | None],
    status: dict[str, str],
    feat: dict,
    profile: str,
    is_financial: bool
) -> list[RedFlag]:
    """Evaluate all flags against the provided metrics, status dict, and features row.

    Args:
        metrics: flat dict name -> value (None = UNKNOWN/NA); raw fund_metrics snapshot
        status: name -> 'OK'|'UNKNOWN'|'NA'; parallel to metrics
        feat: features row dict with keys like pe_ttm, promoter_pct, stmt_age_days, in_gsm, in_asm, in_fo_ban, etc.
        profile: one of GENERAL, BANK, NBFC_FIN, IT_SERVICES, PHARMA, CYCLICAL
        is_financial: True for BANK or NBFC_FIN

    Returns:
        List of RedFlag objects. A flag whose inputs are UNKNOWN/absent is NOT fired.
    """
    flags: list[RedFlag] = []

    # Helper: extract metric value, return None if UNKNOWN/NA
    def m(name: str) -> float | None:
        if metrics.get(name) is None:
            return None
        s = status.get(name, "UNKNOWN")
        if s in ("UNKNOWN", "NA"):
            return None
        return metrics[name]

    # Helper: check if metric is known
    def known(name: str) -> bool:
        return m(name) is not None

    # --- HARD FLAGS ---

    # FORENSIC_BENEISH_2Y: Beneish M > −1.78 in last 2 FYs AND accrual_ratio_sloan > 10% in latest FY
    beneish_m = m("beneish_m")
    beneish_m_prev = m("beneish_m_prev")
    accrual_sloan = m("accrual_ratio_sloan")
    if (known("beneish_m") and known("beneish_m_prev") and known("accrual_ratio_sloan") and
        beneish_m > -1.78 and beneish_m_prev > -1.78 and accrual_sloan > 0.10):
        flags.append(RedFlag(
            "FORENSIC_BENEISH_2Y", "HARD", "SELL",
            f"Beneish M {beneish_m:.2f} (prev {beneish_m_prev:.2f}) > -1.78, accrual {accrual_sloan:.1%} > 10%",
            "statements", beneish_m
        ))

    # FORENSIC_CASH_DIVERGENCE: accrual_ratio_sloan > 15% in each of last 2 FYs AND cfo_to_pat_5y < 0.5
    accrual_sloan_abs = m("accrual_ratio_sloan_abs")
    cfo_pat = m("cfo_to_pat_5y")
    if (known("accrual_ratio_sloan_abs") and cfo_pat is not None and
        accrual_sloan_abs > 0.15 and cfo_pat < 0.5 and not is_financial):
        flags.append(RedFlag(
            "FORENSIC_CASH_DIVERGENCE", "HARD", "SELL",
            f"accrual {accrual_sloan_abs:.1%} > 15%, CFO/PAT {cfo_pat:.2f} < 0.5",
            "statements", accrual_sloan_abs
        ))

    # SOLVENCY_BREACH: non-fin only
    if not is_financial:
        altman = m("altman_zpp")
        int_cover = m("int_cover_ttm")
        net_debt_ebitda = m("net_debt_ebitda")
        if (known("altman_zpp") and known("int_cover_ttm") and
            altman < 1.1 and int_cover < 1.5):
            flags.append(RedFlag(
                "SOLVENCY_BREACH", "HARD", "SELL",
                f"Altman Z'' {altman:.2f} < 1.1, int cover {int_cover:.2f} < 1.5",
                "statements", altman
            ))
        elif (known("net_debt_ebitda") and known("int_cover_ttm") and
              net_debt_ebitda > 6.0 and int_cover < 1.0):
            flags.append(RedFlag(
                "SOLVENCY_BREACH", "HARD", "SELL",
                f"net debt/EBITDA {net_debt_ebitda:.1f} > 6, int cover {int_cover:.2f} < 1.0",
                "statements", net_debt_ebitda
            ))

    # CAPITAL_BREACH_BANK: financial only
    if is_financial:
        gnpa = m("gnpa_pct")
        cet1 = m("cet1_pct")
        if known("gnpa_pct") and gnpa > 10.0:
            flags.append(RedFlag(
                "CAPITAL_BREACH_BANK", "HARD", "SELL",
                f"GNPA {gnpa:.1f}% > 10%",
                "statements", gnpa
            ))
        elif known("cet1_pct") and cet1 < 8.0:
            flags.append(RedFlag(
                "CAPITAL_BREACH_BANK", "HARD", "SELL",
                f"CET1 {cet1:.1f}% < 8%",
                "xbrl", cet1
            ))

    # AUDIT_QUALIFIED_OR_RESIGNED: from feat audit_opinion_clean and auditor_resigned_12m
    audit_opinion = feat.get("audit_opinion_clean")
    auditor_resigned = feat.get("auditor_resigned_12m")
    if (audit_opinion is not None and audit_opinion == 0) or (auditor_resigned and auditor_resigned > 0):
        flags.append(RedFlag(
            "AUDIT_QUALIFIED_OR_RESIGNED", "HARD", "SELL",
            "audit opinion not clean or auditor resigned in 12m",
            "xbrl"
        ))

    # DEFAULT_EVENT: from feat default_event_90d
    default_event = feat.get("default_event_90d")
    if default_event and default_event > 0:
        flags.append(RedFlag(
            "DEFAULT_EVENT", "HARD", "SELL",
            "default event ≤ 90 days",
            "credit_ratings"
        ))

    # PLEDGE_GT_50: pledged_pct_of_promoter > 50
    pledge_pct = m("pledged_pct_of_promoter")
    if known("pledged_pct_of_promoter") and pledge_pct > 50.0:
        flags.append(RedFlag(
            "PLEDGE_GT_50", "HARD", "SELL",
            f"pledged {pledge_pct:.1f}% > 50% of promoter holding",
            "pledges", pledge_pct
        ))

    # GSM: on surveillance GSM list
    gsm = feat.get("in_gsm")
    if gsm:
        flags.append(RedFlag(
            "GSM", "HARD", "SELL",
            "on GSM surveillance list",
            "surveillance"
        ))

    # --- SOFT FLAGS ---

    # BENEISH_1Y: Beneish M > −1.78 in latest FY only (not in both)
    if (known("beneish_m") and beneish_m > -1.78 and
        (not known("beneish_m_prev") or beneish_m_prev <= -1.78)):
        flags.append(RedFlag(
            "BENEISH_1Y", "SOFT", "HOLD",
            f"Beneish M {beneish_m:.2f} > -1.78 in latest FY only",
            "statements", beneish_m
        ))

    # STALE_STATEMENTS: stmt_age_days > 200 (> 400 → NO_RATING handled by confidence layer)
    stmt_age = feat.get("stmt_age_days")
    if stmt_age is not None and 200 < stmt_age <= 400:
        flags.append(RedFlag(
            "STALE_STATEMENTS", "SOFT", "HOLD",
            f"statements {stmt_age} days old",
            "statements"
        ))

    # PROMOTER_SELLING: promoter_chg_1y ≤ −5 pp and no ofs_matched
    promoter_chg = feat.get("promoter_chg_1y")
    ofs_matched = feat.get("ofs_matched")
    if (promoter_chg is not None and promoter_chg <= -5.0 and
        (ofs_matched is None or ofs_matched == 0)):
        flags.append(RedFlag(
            "PROMOTER_SELLING", "SOFT", "HOLD",
            f"promoter selling {promoter_chg:.1f} pp, no matched bulk deal",
            "shareholding", promoter_chg
        ))

    # MOAT_EROSION: spread_ttm < 0 after spread_median_5y > 5%, or OPM down > 500 bp over 3y with sales growing
    spread_ttm = m("spread_ttm")
    spread_median = m("spread_median_5y")
    opm_chg = m("opm_chg_3y")
    if (known("spread_ttm") and known("spread_median_5y") and
        spread_ttm < 0.0 and spread_median > 0.05):
        flags.append(RedFlag(
            "MOAT_EROSION", "SOFT", "HOLD",
            f"spread TTM {spread_ttm:.2%} < 0, median 5y {spread_median:.2%} > 5%",
            "statements", spread_ttm
        ))
    elif opm_chg is not None and opm_chg < -5.0 and m("sales_growth_3y_pos") == 1.0:   # -500 bp with sales growing
        flags.append(RedFlag(
            "MOAT_EROSION", "SOFT", "HOLD",
            f"OPM down {opm_chg:.1f} pp over 3y while sales grew",
            "statements", opm_chg
        ))

    # DEBT_SPIKE: net_debt_ebitda rose by > 2.0 turns in 12m
    net_debt_prev = m("net_debt_ebitda_prev")
    if (known("net_debt_ebitda") and known("net_debt_ebitda_prev") and
        net_debt_ebitda - net_debt_prev > 2.0):
        flags.append(RedFlag(
            "DEBT_SPIKE", "SOFT", "HOLD",
            f"net debt/EBITDA rose {net_debt_ebitda - net_debt_prev:.1f} turns in 12m",
            "statements", net_debt_ebitda - net_debt_prev
        ))

    # OTHER_INCOME_DEPENDENCE: other_income_share > 50% for 2 FYs
    other_income = m("other_income_share")
    other_income_prev = m("other_income_share_prev")
    if (known("other_income_share") and known("other_income_share_prev") and
        other_income > 0.50 and other_income_prev > 0.50):
        flags.append(RedFlag(
            "OTHER_INCOME_DEPENDENCE", "SOFT", "HOLD",
            f"other income share {other_income:.1%} (prev {other_income_prev:.1%}) > 50% for 2 FYs",
            "statements", other_income
        ))

    # LEVERAGED_BUYBACK: buyback while net_debt_ebitda > 3
    leveraged_buyback = feat.get("leveraged_buyback")
    if leveraged_buyback:
        flags.append(RedFlag(
            "LEVERAGED_BUYBACK", "SOFT", "TRIM",
            "buyback while levered",
            "announcements"
        ))

    # PLEDGE_GT_25: 25–50%
    if known("pledged_pct_of_promoter") and 25.0 < pledge_pct <= 50.0:
        flags.append(RedFlag(
            "PLEDGE_GT_25", "SOFT", "TRIM",
            f"pledged {pledge_pct:.1f}% in 25-50% range",
            "pledges", pledge_pct
        ))

    # ASM_STAGE_2_PLUS / FO_BAN: from surveillance
    asm = feat.get("in_asm")
    if asm:
        flags.append(RedFlag(
            "ASM_STAGE_2_PLUS", "SOFT", "HOLD",
            "under ASM stage 2+",
            "surveillance"
        ))

    fo_ban = feat.get("in_fo_ban")
    if fo_ban:
        flags.append(RedFlag(
            "FO_BAN", "SOFT", "HOLD",
            "FO ban on as_of",
            "surveillance"
        ))

    # RATING_DOWNGRADE_2N: ≥ 2 notches down in 12m
    rating_migration = m("rating_migration_12m")
    if known("rating_migration_12m") and rating_migration <= -2:
        flags.append(RedFlag(
            "RATING_DOWNGRADE_2N", "SOFT", "HOLD",
            f"rating migration {rating_migration:.0f} notches in 12m",
            "credit_ratings", rating_migration
        ))

    # PHARMA_USFDA_OAI: PHARMA profile only
    if profile == "PHARMA":
        usfda = feat.get("usfda_oai_12m")
        if usfda and usfda > 0:
            flags.append(RedFlag(
                "PHARMA_USFDA_OAI", "SOFT", "HOLD",
                "USFDA warning/OAI in 12m",
                "announcements"
            ))

    # --- WATCH FLAGS ---

    # OTHER_INCOME_25_50: 25–50%
    if known("other_income_share") and 0.25 <= other_income <= 0.50:
        flags.append(RedFlag(
            "OTHER_INCOME_25_50", "WATCH", None,
            f"other income share {other_income:.1%}",
            "statements", other_income
        ))

    # PLEDGE_10_25: 10–25%
    if known("pledged_pct_of_promoter") and 10.0 < pledge_pct <= 25.0:
        flags.append(RedFlag(
            "PLEDGE_10_25", "WATCH", None,
            f"pledged {pledge_pct:.1f}% in 10-25% range",
            "pledges", pledge_pct
        ))

    # PROMOTER_SELLING_2_5PP: −2 to −5 pp
    if (promoter_chg is not None and -5.0 < promoter_chg <= -2.0):
        flags.append(RedFlag(
            "PROMOTER_SELLING_2_5PP", "WATCH", None,
            f"promoter selling {promoter_chg:.1f} pp in -2 to -5 range",
            "shareholding", promoter_chg
        ))

    # BENEISH_WATCH: −2.22 < M ≤ −1.78
    if (known("beneish_m") and -2.22 < beneish_m <= -1.78):
        flags.append(RedFlag(
            "BENEISH_WATCH", "WATCH", None,
            f"Beneish M {beneish_m:.2f} in watch range",
            "statements", beneish_m
        ))

    # WC_DAYS_UP_20: working capital days +20 in 3y
    wc_days_delta = m("wc_days_delta_3y")
    if known("wc_days_delta_3y") and wc_days_delta > 20.0:
        flags.append(RedFlag(
            "WC_DAYS_UP_20", "WATCH", None,
            f"WC days up {wc_days_delta:.0f} days in 3y",
            "statements", wc_days_delta
        ))

    # TAX_GAP: cash tax rate gap > 10 pp for 3 FYs
    tax_gap = m("cash_tax_gap")
    if known("cash_tax_gap") and tax_gap > 0.10:
        flags.append(RedFlag(
            "TAX_GAP", "WATCH", None,
            f"cash tax gap {tax_gap:.1%} > 10 pp",
            "statements", tax_gap
        ))

    # DEBT_UP_1_TURN: net_debt_ebitda up 1 turn in 12m
    if (known("net_debt_ebitda") and known("net_debt_ebitda_prev") and
        0 < net_debt_ebitda - net_debt_prev <= 2.0):
        flags.append(RedFlag(
            "DEBT_UP_1_TURN", "WATCH", None,
            f"net debt/EBITDA up {net_debt_ebitda - net_debt_prev:.1f} turns in 12m",
            "statements", net_debt_ebitda - net_debt_prev
        ))

    return flags
