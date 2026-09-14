import json

from eqr.validate import trials


def test_append_and_read_and_distinct_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("EQR_EXPERIMENTS_DIR", str(tmp_path / "exp"))
    trials.append_trial({"sleeve": "L", "grid": ["L-N20-base-T1cr", "L-N30-base-T1cr"]}, "L")
    trials.append_trial({"sleeve": "L", "grid": ["L-N20-momentum_tilt-T1cr", "L-N20-base-T1cr"]}, "L")
    assert len(trials.read_trials("L")) == 2
    assert trials.distinct_keys("L") == {"L-N20-base-T1cr", "L-N30-base-T1cr", "L-N20-momentum_tilt-T1cr"}


def test_prior_distinct_trials_excludes_the_current_grid(tmp_path, monkeypatch):
    monkeypatch.setenv("EQR_EXPERIMENTS_DIR", str(tmp_path / "exp"))
    trials.append_trial({"grid": ["A", "B", "C"]}, "L")
    assert trials.prior_distinct_trials("L") == 3
    assert trials.prior_distinct_trials("L", exclude={"A", "B", "D"}) == 1   # only C is prior-and-not-current
    assert trials.prior_distinct_trials("S") == 0


def test_seed_from_reports_is_deduped_and_marked_repair(tmp_path, monkeypatch):
    monkeypatch.setenv("EQR_EXPERIMENTS_DIR", str(tmp_path / "exp"))
    reports = tmp_path / "reports"
    (reports / "validate-1").mkdir(parents=True)
    (reports / "validate-1" / "walkforward.json").write_text(json.dumps(
        {"sleeve": "L", "grid": ["L-N20-base-T1cr", "L-N30-base-T1cr"], "start": "2019-01-01",
         "end": "2025-01-01", "holdout_start": "2024-09-01", "costs": {}, "rf_annual": 0.06}))
    (reports / "backtest-1").mkdir(parents=True)
    (reports / "backtest-1" / "report.json").write_text(json.dumps(
        {"config": {"sleeve": {"name": "S", "top_n": 20, "variant": "base", "min_turnover_inr": 3e7},
                    "costs": {}, "rf_annual": 0.06, "start": "2019-01-01", "end": "2025-01-01"}}))
    first = trials.seed_from_reports(reports)
    again = trials.seed_from_reports(reports)
    assert first == {"L": 1, "S": 1} and again == {"L": 0, "S": 0}
    assert trials.read_trials("L")[0]["purpose"] == "repair"
    assert trials.distinct_keys("S") == {"S-N20-base-T3cr"}
