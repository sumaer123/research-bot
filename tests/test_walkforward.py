from datetime import date

from eqr.spine.adjust import refresh_factors
from eqr.strategy.sleeves import SleeveConfig
from eqr.validate.walkforward import WalkForwardConfig, run_walk_forward
from eqr.validate.report import write_walkforward_report
from eqr.validate.costs import ZERO_BROKERAGE
from eqr.validate.acceptance import evaluate
from tests.conftest import make_synthetic_market


def test_walk_forward_on_planted_market(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    planted = {f"S{i:02d}": 0.004 for i in range(31, 41)}
    syms, days = make_synthetic_market(tmp_db, n_symbols=40, n_days=1300, planted=planted, start=date(2018, 1, 1))
    refresh_factors(tmp_db)
    grid = []
    for n in (5, 8):
        for v in ("base", "momentum_tilt"):
            c = SleeveConfig.L(top_n=n, variant=v)
            c.weights = {"z_momentum": 0.85, "z_lowrisk": 0.15}
            c.min_turnover_inr = 1.0
            c.require_positive_pat = False
            grid.append(c)
    wf = WalkForwardConfig(sleeve="L", start=days[300].date(), end=days[-1].date(), holdout_start=date(2022, 6, 1),
                           fold_years=[2020, 2021, 2022], capital=1e6, costs=ZERO_BROKERAGE, grid=grid,
                           robustness_turnover=(1.0,), prior_trials=4)
    out = run_walk_forward(tmp_db, wf)
    assert len(out["folds"]) >= 2 and out["oos"]["sharpe"] > 0
    assert out["rf_annual"] == wf.rf_annual
    assert out["prior_trials"] == 4 and out["dsr"]["n_trials"] == len(out["grid"]) + 4
    assert out["holdout"]["selected"] in out["grid"]
    assert set(c["check"] for c in out["acceptance"]["checks"]) >= {"oos_sharpe", "deflated_sharpe", "capacity"}
    path = write_walkforward_report(tmp_db, out, "wf-test")
    assert (path / "report.md").exists() and (path / "oos_equity.csv").exists()
    assert "ledger" in (path / "report.md").read_text()
    row = tmp_db.execute("SELECT verdict FROM backtests WHERE run_id = 'wf-test'").fetchone()
    assert row and row[0] in ("VALIDATED", "NOT VALIDATED")


def test_acceptance_bar_logic():
    good = {"sharpe": 1.0, "information_ratio": 0.7, "max_drawdown": -0.2, "bench_max_drawdown": -0.3}
    folds = [{"test_days": 200, "test_excess_cagr": 0.05}] * 4
    acc = evaluate(good, folds, {"p_value": 0.01, "n_trials": 6}, [{"sharpe": 0.9, "excess_cagr": 0.02}],
                   {"median_participation": 0.01})
    assert acc["verdict"] == "VALIDATED"
    bad = dict(good, sharpe=0.5)
    assert evaluate(bad, folds, {"p_value": 0.01}, [{"sharpe": 0.9, "excess_cagr": 0.02}], {"median_participation": 0.01})["verdict"] == "NOT VALIDATED"
