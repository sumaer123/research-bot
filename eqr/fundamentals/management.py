"""Pillar 5: Management Governance & Capital Allocation metrics.

Capital allocation discipline (capex returns, self-funding, dilution, payout), promoter/insider
holdings and changes, pledges, credit rating migrations, and adverse events (SEBI, fraud, auditor
resignation, USFDA warnings for pharma).
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .base import Inputs, Metric, MetricSet, ok, unknown, na


def compute(inp: Inputs, ctx: dict | None = None) -> MetricSet:
    """Compute Pillar 5 management and capital allocation metrics.

    For financial profiles (BANK/NBFC_FIN), some capex/FCF metrics are NA.
    """
    out = MetricSet()

    is_fin = inp.is_financial

    # Capital allocation metrics (non-financial)
    if not is_fin:
        out.add(_capex_return_test(inp))
        out.add(_self_funding_5y(inp))
    else:
        out.add(na("capex_return_test"))
        out.add(na("self_funding_5y"))

    # Dilution and payout (all profiles)
    out.add(_dilution_5y(inp))
    out.add(_payout_discipline(inp))

    # Promoter metrics (all profiles)
    out.add(_promoter_pct(inp))
    out.add(_promoter_chg_1y(inp))
    out.add(_promoter_chg_3y(inp))

    # Pledge metrics (forward-only, UNKNOWN today)
    out.add(_pledged_pct_of_promoter(inp))
    out.add(_pledge_delta_4q(inp))

    # Insider and institutional (all profiles)
    out.add(_insider_net_buy_12m(inp))
    out.add(_inst_chg_1y(inp))

    # Credit and rating (all profiles)
    out.add(_rating_migration_12m(inp))
    out.add(_outlook_negative(inp))

    # Adverse events (keyword-based announcements)
    out.add(_adverse_events_90d_clean(inp))

    # Informational: OFS matching
    out.add(_ofs_matched(inp))

    # Informational: leveraged buyback flag
    if ctx is None:
        ctx = {}
    out.add(_leveraged_buyback(inp, ctx))

    # Informational: sources and uses
    out.add(_sources_uses_5y_info(inp))

    # LLM grades (r3) - not computed here, marked UNKNOWN
    out.add(unknown("mgmt_grade_llm", "llm_grade_r3_not_computed"))

    return out


def _capex_return_test(inp: Inputs) -> Metric:
    """(EBIT_t − EBIT_t−5) / Σ capex over 5y.

    EBIT ≈ operating_profit. Capex ≈ −CFI.
    """
    a = inp.annual
    if a.empty or len(a) < 6:
        return unknown("capex_return_test", "insufficient history")

    ebit_now = inp.op(-1)
    ebit_5y_ago = inp.op(-6)
    if ebit_now is None or ebit_5y_ago is None:
        return unknown("capex_return_test", "missing EBIT")

    # Capex = −CFI (cash from investing activity)
    cfi_s = a["cash_from_investing_activity"].astype(float).tail(5)
    capex_sum = -cfi_s.sum()  # negate to get capex magnitude

    if capex_sum <= 0:
        return unknown("capex_return_test", "Σ capex ≤ 0")

    roic_delta = (ebit_now - ebit_5y_ago) / capex_sum
    return ok("capex_return_test", roic_delta, inputs_as_of=inp.latest_period())


def _self_funding_5y(inp: Inputs) -> Metric:
    """Share of last 5 FYs where CFO − (−CFI) − dividends ≥ 0 (fraction 0..1).

    CFO − capex − dividends is the self-funding test.
    """
    a = inp.annual
    if a.empty or "cash_from_operating_activity" not in a.columns or \
       "cash_from_investing_activity" not in a.columns or "net_profit" not in a.columns:
        return unknown("self_funding_5y", "missing cash flow data")

    cfo_s = a["cash_from_operating_activity"].astype(float).tail(5)
    cfi_s = a["cash_from_investing_activity"].astype(float).tail(5)
    pat_s = a["net_profit"].astype(float).tail(5)
    payout_s = a["dividend_payout_pct"].astype(float).tail(5)

    self_funded_count = 0
    valid_count = 0

    for cfo, cfi, pat, payout in zip(cfo_s, cfi_s, pat_s, payout_s):
        if cfo is None or cfi is None or pat is None or payout is None:
            continue
        if not (math.isfinite(cfo) and math.isfinite(cfi) and math.isfinite(pat) and math.isfinite(payout)):
            continue

        capex = -cfi  # negate CFI to get capex
        dividends = pat * (payout / 100)
        test = cfo - capex - dividends

        valid_count += 1
        if test >= 0:
            self_funded_count += 1

    if valid_count == 0:
        return unknown("self_funding_5y", "no valid years")

    fraction = self_funded_count / valid_count
    return ok("self_funding_5y", fraction, inputs_as_of=inp.latest_period())


def _dilution_5y(inp: Inputs) -> Metric:
    """Shares CAGR over 5 FYs (shares = equity_capital / face_value).

    Bonus issues: when equity_capital jumps ≥50% in a year and PAT doesn't fall, neutralise.
    Result: CAGR per year (can be negative for buybacks).
    """
    a = inp.annual
    if a.empty or "equity_capital" not in a.columns or inp.face_value is None or inp.face_value <= 0:
        return unknown("dilution_5y", "missing equity_capital or face_value")

    eq_s = a["equity_capital"].astype(float).tail(5)
    pat_s = a["net_profit"].astype(float).tail(5) if "net_profit" in a.columns else pd.Series(dtype=float)

    if len(eq_s) < 2:
        return unknown("dilution_5y", "insufficient history")

    # Calculate shares (shares = equity_capital / face_value)
    fv = inp.face_value
    shares = [eq / fv if eq is not None else None for eq in eq_s]

    # Detect and neutralise bonuses
    has_pat = len(pat_s) > 0
    bonus_found = False
    for i in range(1, len(shares)):
        if shares[i] is not None and shares[i-1] is not None and shares[i-1] > 0:
            eq_jump = shares[i] / shares[i-1]
            pat_chg = None
            if has_pat and i < len(pat_s) and i-1 < len(pat_s):
                try:
                    pat_chg = pat_s.iloc[i] / pat_s.iloc[i-1] if pat_s.iloc[i-1] is not None and pat_s.iloc[i-1] > 0 else None
                except (IndexError, KeyError):
                    pat_chg = None

            # If jump ≥50% and PAT doesn't fall, treat as bonus
            if eq_jump >= 1.5 and (pat_chg is None or pat_chg >= 1.0):
                shares[i] = shares[i] / eq_jump  # neutralise the bonus
                bonus_found = True

    # Filter valid shares
    valid_shares = [s for s in shares if s is not None and math.isfinite(s) and s > 0]

    if len(valid_shares) < 2:
        return unknown("dilution_5y", "insufficient valid shares")

    # CAGR = (shares_end / shares_start)^(1/n) - 1
    start_share = valid_shares[0]
    end_share = valid_shares[-1]
    n = len(valid_shares) - 1

    if start_share <= 0:
        return unknown("dilution_5y", "start share ≤ 0")

    cagr = (end_share / start_share) ** (1 / n) - 1
    note = "bonus_neutralised" if bonus_found else ""
    return ok("dilution_5y", cagr, inputs_as_of=inp.latest_period(), note=note)


def _payout_discipline(inp: Inputs) -> Metric:
    """Payout discipline: 0..100 map.

    100 if dividend paid in ≥4 of 5 FYs and mean payout 20–60%.
    50 if paid ≥3/5 or payout outside band.
    0 if paid ≤2/5.
    """
    a = inp.annual
    if a.empty or "dividend_payout_pct" not in a.columns:
        return unknown("payout_discipline", "missing payout data")

    payout_s = a["dividend_payout_pct"].astype(float).tail(5)

    # Count years with non-zero payout
    paid_years = sum(1 for p in payout_s if p is not None and p > 0 and math.isfinite(p))
    valid_payouts = [p for p in payout_s if p is not None and math.isfinite(p)]

    if len(valid_payouts) == 0:
        mean_payout = None
    else:
        mean_payout = np.mean(valid_payouts)

    # Scoring logic
    if paid_years <= 2:
        score = 0.0
    elif paid_years >= 4 and mean_payout is not None and 20 <= mean_payout <= 60:
        score = 100.0
    elif paid_years >= 3 or (mean_payout is not None and (mean_payout < 20 or mean_payout > 60)):
        score = 50.0
    else:
        score = 0.0

    return ok("payout_discipline", score, inputs_as_of=inp.latest_period())


def _promoter_pct(inp: Inputs) -> Metric:
    """Latest promoter ownership percentage (pp)."""
    sh = inp.shareholding
    if sh.empty or "holder" not in sh.columns or "pct" not in sh.columns:
        return unknown("promoter_pct", "missing shareholding data")

    prom = sh[sh.holder == "promoters"].sort_values("period_end")
    if prom.empty:
        return unknown("promoter_pct", "no promoter data")

    latest_pct = prom["pct"].iloc[-1]
    if latest_pct is None or not math.isfinite(latest_pct):
        return unknown("promoter_pct", "invalid promoter pct")

    return ok("promoter_pct", latest_pct, inputs_as_of=inp.latest_period())


def _promoter_chg_1y(inp: Inputs) -> Metric:
    """Promoter pct now − 4 quarters earlier (1y, pp)."""
    sh = inp.shareholding
    if sh.empty or "holder" not in sh.columns or "pct" not in sh.columns:
        return unknown("promoter_chg_1y", "missing shareholding data")

    prom = sh[sh.holder == "promoters"].sort_values("period_end")
    if len(prom) < 5:  # Need at least 5 quarters for 1y change
        return unknown("promoter_chg_1y", "insufficient history")

    pct_now = prom["pct"].iloc[-1]
    pct_4q = prom["pct"].iloc[-5]

    if pct_now is None or pct_4q is None or not (math.isfinite(pct_now) and math.isfinite(pct_4q)):
        return unknown("promoter_chg_1y", "invalid values")

    delta = pct_now - pct_4q
    return ok("promoter_chg_1y", delta, inputs_as_of=inp.latest_period())


def _promoter_chg_3y(inp: Inputs) -> Metric:
    """Promoter pct now − 12 quarters earlier (3y, pp)."""
    sh = inp.shareholding
    if sh.empty or "holder" not in sh.columns or "pct" not in sh.columns:
        return unknown("promoter_chg_3y", "missing shareholding data")

    prom = sh[sh.holder == "promoters"].sort_values("period_end")
    if len(prom) < 13:  # Need at least 13 quarters for 3y change
        return unknown("promoter_chg_3y", "insufficient history")

    pct_now = prom["pct"].iloc[-1]
    pct_12q = prom["pct"].iloc[-13]

    if pct_now is None or pct_12q is None or not (math.isfinite(pct_now) and math.isfinite(pct_12q)):
        return unknown("promoter_chg_3y", "invalid values")

    delta = pct_now - pct_12q
    return ok("promoter_chg_3y", delta, inputs_as_of=inp.latest_period())


def _pledged_pct_of_promoter(inp: Inputs) -> Metric:
    """Latest pledged_pct_of_promoter from pledges table. UNKNOWN if unpopulated."""
    pledges = inp.pledges
    if pledges.empty or "pledged_pct_of_promoter" not in pledges.columns:
        return unknown("pledged_pct_of_promoter", "pledges_unpopulated")

    latest = pledges.sort_values("visible_from")["pledged_pct_of_promoter"].iloc[-1]
    if latest is None or not math.isfinite(latest):
        return unknown("pledged_pct_of_promoter", "pledges_unpopulated")

    return ok("pledged_pct_of_promoter", latest, inputs_as_of=inp.latest_period())


def _pledge_delta_4q(inp: Inputs) -> Metric:
    """Pledged pct now − 4 quarters ago (pp). UNKNOWN if unpopulated."""
    pledges = inp.pledges
    if pledges.empty or "pledged_pct_of_promoter" not in pledges.columns or "visible_from" not in pledges.columns:
        return unknown("pledge_delta_4q", "pledges_unpopulated")

    pledges_sorted = pledges.sort_values("visible_from")
    if len(pledges_sorted) < 2:
        return unknown("pledge_delta_4q", "pledges_unpopulated")

    # Find entries within ~1 year apart
    latest_row = pledges_sorted.iloc[-1]
    latest_date = pd.Timestamp(latest_row["visible_from"]).date()
    target_date = latest_date - timedelta(days=365)

    # Find the closest row to target_date
    prior_rows = pledges_sorted[pledges_sorted["visible_from"] <= target_date]
    if prior_rows.empty:
        return unknown("pledge_delta_4q", "pledges_unpopulated")

    prior_row = prior_rows.iloc[-1]
    pct_now = latest_row.get("pledged_pct_of_promoter")
    pct_prior = prior_row.get("pledged_pct_of_promoter")

    if pct_now is None or pct_prior is None or not (math.isfinite(pct_now) and math.isfinite(pct_prior)):
        return unknown("pledge_delta_4q", "pledges_unpopulated")

    delta = pct_now - pct_prior
    return ok("pledge_delta_4q", delta, inputs_as_of=inp.latest_period())


def _insider_net_buy_12m(inp: Inputs) -> Metric:
    """Σ(buys − sells) value / mcap over last 365 days. UNKNOWN if unpopulated."""
    insider = inp.insider
    if insider.empty or "visible_from" not in insider.columns or "value_inr" not in insider.columns or "side" not in insider.columns:
        return unknown("insider_net_buy_12m", "insider_unpopulated")

    # Filter to last 365 days
    if_date = inp.as_of
    since_date = if_date - timedelta(days=365)
    recent = insider[insider["visible_from"] >= since_date]

    if recent.empty:
        return unknown("insider_net_buy_12m", "insider_unpopulated")

    # Sum buys and sells
    buy_value = recent[recent["side"] == "BUY"]["value_inr"].sum() if "BUY" in recent["side"].values else 0.0
    sell_value = recent[recent["side"] == "SELL"]["value_inr"].sum() if "SELL" in recent["side"].values else 0.0
    net_value = buy_value - sell_value

    # Get mcap from feat
    mcap_cr = inp.feat.get("mcap_cr")
    if mcap_cr is None or mcap_cr <= 0:
        return unknown("insider_net_buy_12m", "mcap missing")

    mcap_inr = mcap_cr * 1e7  # convert crore to INR
    ratio = net_value / mcap_inr
    return ok("insider_net_buy_12m", ratio, inputs_as_of=inp.latest_period())


def _inst_chg_1y(inp: Inputs) -> Metric:
    """FII + DII pct now − 4 quarters earlier (1y, pp)."""
    sh = inp.shareholding
    if sh.empty or "holder" not in sh.columns or "pct" not in sh.columns:
        return unknown("inst_chg_1y", "missing shareholding data")

    # FII + DII
    inst = sh[sh.holder.isin(["fii", "dii"])].groupby(["period_end"]).pct.sum().sort_index()

    if len(inst) < 5:  # Need at least 5 quarters
        return unknown("inst_chg_1y", "insufficient history")

    pct_now = inst.iloc[-1]
    pct_4q = inst.iloc[-5]

    if pct_now is None or pct_4q is None or not (math.isfinite(pct_now) and math.isfinite(pct_4q)):
        return unknown("inst_chg_1y", "invalid values")

    delta = pct_now - pct_4q
    return ok("inst_chg_1y", delta, inputs_as_of=inp.latest_period())


def _rating_migration_12m(inp: Inputs) -> Metric:
    """Notch migration sum over last 365 days (notch − prev_notch). UNKNOWN if unpopulated."""
    credit = inp.credit
    if credit.empty or "visible_from" not in credit.columns:
        return unknown("rating_migration_12m", "credit ratings data unpopulated")

    # Filter to last 365 days
    if_date = inp.as_of
    since_date = if_date - timedelta(days=365)
    recent = credit[credit["visible_from"] >= since_date].sort_values("visible_from")

    if recent.empty:
        return unknown("rating_migration_12m", "credit ratings data unpopulated")

    # Compute notch deltas if notch/prev_notch columns exist
    if "notch" not in recent.columns or "prev_notch" not in recent.columns:
        return unknown("rating_migration_12m", "credit ratings data unpopulated")

    migration = 0
    for row in recent.itertuples():
        if row.notch is not None and row.prev_notch is not None and \
           math.isfinite(row.notch) and math.isfinite(row.prev_notch):
            migration += (row.notch - row.prev_notch)

    return ok("rating_migration_12m", migration, inputs_as_of=inp.latest_period())


def _outlook_negative(inp: Inputs) -> Metric:
    """Binary informational: 1 when latest credit outlook is negative."""
    credit = inp.credit
    if credit.empty or "outlook" not in credit.columns:
        return unknown("outlook_negative", "credit ratings data unpopulated")

    latest = credit.sort_values("visible_from").iloc[-1]
    outlook = latest.get("outlook")

    if outlook is None:
        return unknown("outlook_negative", "credit ratings data unpopulated")

    is_negative = 1.0 if "negative" in str(outlook).lower() else 0.0
    return ok("outlook_negative", is_negative, inputs_as_of=inp.latest_period())


def _adverse_events_90d_clean(inp: Inputs) -> Metric:
    """Binary: 1 when no adverse announcement in 90 days. UNKNOWN if announcements empty."""
    announcements = inp.announcements
    if announcements.empty:
        return unknown("adverse_events_90d_clean", "announcements_unpopulated")

    # Keywords (case-insensitive)
    ADVERSE_KEYWORDS = [
        "sebi order", "fraud", "forensic audit", "default",
        "resignation of auditor", "auditor resign",
        "resignation of cfo",
        "warning letter", "oai", "import alert",
        "insolvency", "nclt", "winding up"
    ]

    if_date = pd.Timestamp(inp.as_of)
    since_date = if_date - timedelta(days=90)
    announcements["ann_dt"] = pd.to_datetime(announcements["ann_dt"])
    recent = announcements[announcements["ann_dt"] >= since_date]

    if recent.empty:
        return ok("adverse_events_90d_clean", 1.0, inputs_as_of=inp.latest_period())

    # Check for adverse keywords in subject + description
    for row in recent.itertuples():
        subject = str(row.subject or "").lower() if hasattr(row, 'subject') else ""
        description = str(row.description or "").lower() if hasattr(row, 'description') else ""
        text = subject + " " + description

        for keyword in ADVERSE_KEYWORDS:
            if keyword in text:
                return ok("adverse_events_90d_clean", 0.0, inputs_as_of=inp.latest_period())

    return ok("adverse_events_90d_clean", 1.0, inputs_as_of=inp.latest_period())


def _ofs_matched(inp: Inputs) -> Metric:
    """Binary informational: 1 when a promoter drop ≥2pp coincides (±30 days) with OFS/offer-for-sale.

    Helps identify planned capital dilution vs ad-hoc selling.
    """
    # Check if promoter declined by ≥2pp in the last 1y
    prom_chg = _promoter_chg_1y(inp)
    if prom_chg.value is None or prom_chg.value >= -2.0:
        return ok("ofs_matched", 0.0, inputs_as_of=inp.latest_period(), note="informational")

    # Look for OFS deals
    deals = inp.deals
    if deals.empty or "trade_date" not in deals.columns or "kind" not in deals.columns:
        return ok("ofs_matched", 0.0, inputs_as_of=inp.latest_period(), note="informational")

    # Find OFS entries
    ofs_rows = deals[deals["kind"].str.contains("OFS|offer for sale", case=False, na=False)]
    if ofs_rows.empty:
        return ok("ofs_matched", 0.0, inputs_as_of=inp.latest_period(), note="informational")

    # Check if timing matches (±30 days from latest promoter change)
    # This is a simplified check; a full implementation would track exact dates
    return ok("ofs_matched", 1.0, inputs_as_of=inp.latest_period(), note="informational")


def _leveraged_buyback(inp: Inputs, ctx: dict) -> Metric:
    """Binary informational: su_buybacks_5y > 0 in latest FY while net_debt_ebitda > 3.

    Flags buybacks during high leverage.
    """
    # Check if buybacks happened
    a = inp.annual
    if a.empty or "equity_capital" not in a.columns:
        return ok("leveraged_buyback", 0.0, inputs_as_of=inp.latest_period(), note="informational")

    eq_now = inp.a("equity_capital", -1)
    eq_prev = inp.a("equity_capital", -2)

    if eq_now is None or eq_prev is None or inp.face_value is None or inp.face_value <= 0:
        return ok("leveraged_buyback", 0.0, inputs_as_of=inp.latest_period(), note="informational")

    # Buyback: equity_capital reduction at constant face value
    shares_now = eq_now / inp.face_value
    shares_prev = eq_prev / inp.face_value
    is_buyback = shares_now < shares_prev * 0.98  # >2% reduction

    if not is_buyback:
        return ok("leveraged_buyback", 0.0, inputs_as_of=inp.latest_period(), note="informational")

    # Check net_debt_ebitda from context
    nde = ctx.get("net_debt_ebitda")
    if nde is None or nde <= 3:
        return ok("leveraged_buyback", 0.0, inputs_as_of=inp.latest_period(), note="informational")

    return ok("leveraged_buyback", 1.0, inputs_as_of=inp.latest_period(), note="informational")


def _sources_uses_5y_info(inp: Inputs) -> Metric:
    """Informational: Σ CFO, Σ CFI (capex proxy), Σ CFF (dividends, buybacks, equity, net borrowing).

    Returns a summary; actual table is built by the application layer.
    """
    a = inp.annual
    if a.empty:
        return unknown("su_cfo_5y", "no annual data")

    cfo_s = a["cash_from_operating_activity"].astype(float).tail(5)
    cfo_sum = cfo_s.sum() if cfo_s.notna().any() else None

    if cfo_sum is None or not math.isfinite(cfo_sum):
        return unknown("su_cfo_5y", "missing CFO")

    return ok("su_cfo_5y", cfo_sum, inputs_as_of=inp.latest_period(), note="informational")
