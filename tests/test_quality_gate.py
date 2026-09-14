import json
from datetime import date, datetime

import pytest

from eqr.spine.quality import severity
from eqr.store.quality_gate import assert_quality, QualityBlocked, record_forced


def _add_check(con, as_of, name, status, run_id="qc-1"):
    con.execute("INSERT INTO quality_checks VALUES (?, ?, ?, ?, ?, ?)",
                [run_id, as_of, name, status, "detail", datetime.now()])


def test_severity_map_marks_the_four_blockers():
    assert severity("bhavcopy_eq_rows") == "BLOCKER"
    assert severity("no_duplicate_price_keys") == "BLOCKER"
    assert severity("required_indices_present") == "BLOCKER"
    assert severity("unexplained_price_jumps") == "BLOCKER"
    assert severity("delivery_coverage") == "WARN"
    assert severity("xbrl_freshness") == "WARN"


def test_gate_passes_when_only_warns_fail(tmp_db):
    d = date(2026, 9, 12)
    _add_check(tmp_db, d, "delivery_coverage", "FAIL")
    _add_check(tmp_db, d, "bhavcopy_eq_rows", "PASS")
    out = assert_quality(tmp_db, d, "backtest")
    assert out["ok"] and not out["forced"] and out["blockers"] == []


def test_gate_refuses_on_an_unresolved_blocker(tmp_db):
    d = date(2026, 9, 12)
    _add_check(tmp_db, d, "bhavcopy_eq_rows", "FAIL")
    with pytest.raises(QualityBlocked):
        assert_quality(tmp_db, d, "validate")


def test_force_bypasses_the_blocker_and_records_the_reason(tmp_db):
    d = date(2026, 9, 12)
    _add_check(tmp_db, d, "no_duplicate_price_keys", "FAIL")
    out = assert_quality(tmp_db, d, "rank", force_reason="known synthetic gap")
    assert out["ok"] and out["forced"] and out["forced_reason"] == "known synthetic gap"
    assert [b["check"] for b in out["blockers"]] == ["no_duplicate_price_keys"]
    # record_forced stamps the backtests row's params so the run is non-validatable
    tmp_db.execute("INSERT INTO backtests (run_id, sleeve, params, verdict, created_at) VALUES (?, ?, ?, ?, ?)",
                   ["bt-forced", "L", json.dumps({"capital": 1e6}), "VALIDATED", datetime.now()])
    record_forced(tmp_db, "bt-forced", "known synthetic gap")
    params = json.loads(tmp_db.execute("SELECT params FROM backtests WHERE run_id = 'bt-forced'").fetchone()[0])
    assert params["forced_reason"] == "known synthetic gap"


def test_gate_ignores_a_newer_quality_run_after_the_as_of(tmp_db):
    _add_check(tmp_db, date(2026, 9, 10), "bhavcopy_eq_rows", "PASS", run_id="old")
    _add_check(tmp_db, date(2026, 9, 20), "bhavcopy_eq_rows", "FAIL", run_id="new")
    # a backtest ending 2026-09-12 only sees the clean run on/before that date
    out = assert_quality(tmp_db, date(2026, 9, 12), "backtest")
    assert out["ok"] and out["blockers"] == []
