import numpy as np
import pandas as pd

from eqr.validate.costs import CostModel, ZERO_BROKERAGE
from eqr.validate.metrics import deflated_sharpe, sharpe, max_drawdown, cagr, summarize


def test_order_cost_hand_computed():
    cm = CostModel()
    c = cm.order_cost("BUY", 100000.0, adv20=1e8)      # 0.1% participation
    # explicit: brokerage 20 + STT 100 + exch 2.97 + SEBI 0.1 + stamp 15 + GST 18% of (20+2.97+0.1)=4.15
    assert abs(c["explicit"] - (20 + 100 + 2.97 + 0.1 + 15 + 4.1526)) < 0.05
    # impact: 10 + 50*sqrt(0.001) = 11.58 bps -> 115.8
    assert abs(c["impact"] - 115.8) < 0.5
    s = cm.order_cost("SELL", 100000.0, adv20=1e8)
    assert s["dp"] == 15.34 and s["stamp"] == 0
    big = cm.order_cost("BUY", 5e7, adv20=1e8)             # 50% participation -> 45.36 bps
    assert abs(big["impact"] - 5e7 * 0.0045355) < 5
    assert ZERO_BROKERAGE.order_cost("BUY", 1e5, 1e8)["brokerage"] == 0


def test_sharpe_and_dsr_known_behaviour():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2018-01-01", periods=1500)
    good = pd.Series(rng.normal(0.0012, 0.01, len(idx)), index=idx)      # ~SR 1.6
    noise = pd.Series(rng.normal(0.0, 0.01, len(idx)), index=idx)
    assert sharpe(good) > 1.0 and abs(sharpe(noise)) < 1.5
    var = (0.3 / np.sqrt(252)) ** 2                        # trial SRs spread ~0.3 annualised
    d_good = deflated_sharpe(good, n_trials=6, trial_sr_var=var)
    d_noise = deflated_sharpe(noise, n_trials=6, trial_sr_var=var)
    assert d_good["p_value"] < 0.05 and d_noise["p_value"] > 0.05
    assert d_good["sr0_annual"] > 0 and deflated_sharpe(good, n_trials=1)["sr0_annual"] == 0
    # the conservative default (no trial variance given) must be harder to pass, never easier
    assert deflated_sharpe(good, n_trials=6)["p_value"] >= d_good["p_value"]
    eq = (1 + good).cumprod() * 100
    assert 0 < cagr(eq) < 1 and -0.5 < max_drawdown(eq) < 0
    s = summarize(eq, bench_equity=(1 + noise).cumprod() * 100)
    assert s["information_ratio"] > 0 and "tracking_error" in s
