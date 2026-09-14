import json
from datetime import datetime

from eqr.validate.claims import claim_state, ClaimState, open_item_codes, is_validated


def _put_backtest(con, sleeve, verdict, params=None, run_id="v1", created=None):
    con.execute("INSERT INTO backtests (run_id, sleeve, params, verdict, created_at) VALUES (?, ?, ?, ?, ?)",
                [run_id, sleeve, json.dumps(params or {}), verdict, created or datetime.now()])


def test_ladder_transitions(tmp_db):
    assert claim_state(tmp_db, "L")[0] == ClaimState.DIAGNOSTIC                 # no run
    _put_backtest(tmp_db, "S", "NOT VALIDATED", run_id="s1")
    assert claim_state(tmp_db, "S")[0] == ClaimState.DIAGNOSTIC                 # bar failed
    _put_backtest(tmp_db, "L", "VALIDATED", run_id="l1")
    st, reasons = claim_state(tmp_db, "L")
    assert st == ClaimState.PROVISIONAL and set(reasons) == set(open_item_codes())
    _put_backtest(tmp_db, "L", "VALIDATED", params={"forced_reason": "quality gap"},
                  run_id="l2", created=datetime(2030, 1, 1))
    assert claim_state(tmp_db, "L")[0] == ClaimState.DIAGNOSTIC                 # latest run was forced


def test_backtest_pass_only_when_every_integrity_item_is_closed(tmp_db, monkeypatch):
    _put_backtest(tmp_db, "L", "VALIDATED", run_id="l1")
    monkeypatch.setattr("eqr.validate.claims.open_item_codes", lambda: [])
    st, reasons = claim_state(tmp_db, "L")
    assert st == ClaimState.BACKTEST_PASS and reasons == [] and is_validated(st)


def test_prospective_validated_never_comes_from_a_backtest_row(tmp_db):
    # a VALIDATED backtest with no matured forward rows can never reach PROSPECTIVE_VALIDATED
    _put_backtest(tmp_db, "L", "VALIDATED", run_id="l1")
    assert claim_state(tmp_db, "L")[0] == ClaimState.PROVISIONAL


def test_is_validated_only_for_pass_states():
    assert is_validated(ClaimState.BACKTEST_PASS) and is_validated(ClaimState.PROSPECTIVE_VALIDATED)
    assert not is_validated(ClaimState.PROVISIONAL) and not is_validated(ClaimState.DIAGNOSTIC)
