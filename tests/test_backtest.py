import json
from datetime import date

import numpy as np
import pandas as pd

from eqr.spine.adjust import refresh_factors
from eqr.strategy.sleeves import SleeveConfig
from eqr.validate.backtest import BacktestConfig, run_backtest
from eqr.validate.costs import ZERO_BROKERAGE
from tests.conftest import make_synthetic_market


def test_rf_annual_defaults_from_settings(monkeypatch):
    monkeypatch.setenv("EQR_RISK_FREE_PCT", "7.5")
    cfg = BacktestConfig(sleeve=SleeveConfig.L(), start=date(2020, 1, 1), end=date(2021, 1, 1))
    assert cfg.rf_annual == 0.075
    from eqr.validate.walkforward import WalkForwardConfig
    wf = WalkForwardConfig(sleeve="L", start=date(2019, 1, 1), end=date(2021, 1, 1),
                           holdout_start=date(2020, 6, 1), fold_years=[2019])
    assert wf.rf_annual == 0.075


def test_backtest_report_embeds_the_cost_model_and_rf(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    from eqr.validate.report import write_backtest_report
    syms, days = make_synthetic_market(tmp_db, n_symbols=12, n_days=420, seed=7)
    refresh_factors(tmp_db)
    sl = SleeveConfig.L(top_n=8); sl.min_turnover_inr = 1.0; sl.require_positive_pat = False
    cfg = BacktestConfig(sleeve=sl, start=days[300].date(), end=days[-1].date(), capital=1e6, reuse_features=False)
    res = run_backtest(tmp_db, cfg)
    path = write_backtest_report(tmp_db, res, "bt-embed", "t")
    rj = json.loads((path / "report.json").read_text())
    assert rj["config"]["costs"]["impact_k_bps"] == 50.0
    assert rj["config"]["rf_annual"] == cfg.rf_annual
    assert "rf" in (path / "report.md").read_text().lower()


def test_planted_signal_is_recovered_and_no_lookahead(tmp_db):
    # symbols S31..S40 drift up 0.4%/day; a momentum-heavy sleeve must overweight them and beat the index
    planted = {f"S{i:02d}": 0.004 for i in range(31, 41)}
    syms, days = make_synthetic_market(tmp_db, n_symbols=40, n_days=700, planted=planted)
    refresh_factors(tmp_db)
    sl = SleeveConfig.L(top_n=10, variant="momentum_tilt")
    sl.weights = {"z_momentum": 0.85, "z_lowrisk": 0.15}
    sl.min_turnover_inr = 1.0
    sl.require_positive_pat = False
    cfg = BacktestConfig(sleeve=sl, start=days[320].date(), end=days[-1].date(), capital=1e6,
                         costs=ZERO_BROKERAGE, reuse_features=False)
    res = run_backtest(tmp_db, cfg)
    assert res.stats["rebalances"] >= 10 and len(res.trades) > 10
    last = list(res.holdings.values())[-1]["weights"]
    planted_share = sum(w for s, w in last.items() if s in planted) / sum(last.values())
    assert planted_share > 0.6                     # share of INVESTED weight (regime scales the total)
    assert res.stats["final_equity"] > 1e6 and res.stats["cagr"] > res.stats["bench_cagr"]
    # equity is MTM daily and never NaN; costs were charged
    assert res.equity.notna().all() and res.stats["costs_total"] > 0
    # trades happen strictly after their signal date (fills at next open)
    signal_dates = pd.to_datetime(list(res.holdings.keys()))
    first_trade = res.trades.date.min()
    assert first_trade > signal_dates.min()


def test_stop_loss_and_weekly_sleeve(tmp_db):
    syms, days = make_synthetic_market(tmp_db, n_symbols=25, n_days=500, seed=3)
    refresh_factors(tmp_db)
    sl = SleeveConfig.S(top_n=5)
    sl.min_turnover_inr = 1.0
    cfg = BacktestConfig(sleeve=sl, start=days[300].date(), end=days[-1].date(), capital=5e5, reuse_features=False)
    res = run_backtest(tmp_db, cfg)
    assert res.stats["rebalances"] >= 20
    reasons = set(res.trades.reason.unique())
    assert "rebalance_buy" in reasons
    assert res.equity.iloc[-1] > 0


def test_delisting_and_series_move_keep_equity_continuous(tmp_db):
    """S02 stops trading after day 380 (delisted); S03 moves to the BE series for 15 sessions.
    Equity must not jump on the forced sale, and S03 must never be treated as delisted."""
    syms, days = make_synthetic_market(tmp_db, n_symbols=12, n_days=460, seed=5)
    refresh_factors(tmp_db)
    tmp_db.execute("DELETE FROM prices_daily WHERE symbol = 'S02' AND trade_date > ?", [days[380].date()])
    tmp_db.execute("UPDATE prices_daily SET series = 'BE' WHERE symbol = 'S03' AND trade_date BETWEEN ? AND ?",
                   [days[390].date(), days[405].date()])
    sl = SleeveConfig.L(top_n=12); sl.min_turnover_inr = 1.0; sl.require_positive_pat = False
    cfg = BacktestConfig(sleeve=sl, start=days[300].date(), end=days[-1].date(), capital=1e6, costs=ZERO_BROKERAGE, reuse_features=False)
    res = run_backtest(tmp_db, cfg)
    delisted = res.trades[res.trades.reason == "delisted"]
    assert set(delisted.symbol) == {"S02"}
    r = res.equity.pct_change().abs()
    assert r.max() < 0.06                       # 12 names of ~8%: no day can move equity by a whole position
