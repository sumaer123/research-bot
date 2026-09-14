from datetime import date

import duckdb
import pandas as pd
import pytest

from eqr.store import upsert, query, new_run, end_run, table_columns
from eqr.store.db import init_schema, _primary_key
from eqr.store.pit import statements_as_of

_LEGACY_DOSSIERS = ("CREATE TABLE dossiers (symbol VARCHAR, as_of DATE, model VARCHAR, rating VARCHAR, "
                    "confidence DOUBLE, json VARCHAR, markdown VARCHAR, created_at TIMESTAMP, "
                    "PRIMARY KEY (symbol, as_of))")


def test_durable_data_tables_have_the_corrected_primary_keys(tmp_db):
    assert _primary_key(tmp_db, "dossiers") == ["run_id"]
    assert _primary_key(tmp_db, "fund_metrics") == ["as_of", "symbol", "metric", "engine_version"]
    assert _primary_key(tmp_db, "dossier_claims") == ["run_id", "claim_id"]


def test_dossiers_current_view_exists_and_is_empty_on_fresh_db(tmp_db):
    views = {r[0] for r in tmp_db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_type = 'VIEW'").fetchall()}
    assert "dossiers_current" in views
    assert tmp_db.execute("SELECT count(*) FROM dossiers_current").fetchone()[0] == 0


def test_reconcile_recreates_an_empty_legacy_dossiers_table(tmp_path):
    con = duckdb.connect(str(tmp_path / "legacy.duckdb"))
    con.execute(_LEGACY_DOSSIERS)
    assert _primary_key(con, "dossiers") == ["symbol", "as_of"]
    init_schema(con)
    assert _primary_key(con, "dossiers") == ["run_id"]
    con.close()


def test_reconcile_is_idempotent(tmp_db):
    init_schema(tmp_db)
    init_schema(tmp_db)
    assert _primary_key(tmp_db, "dossiers") == ["run_id"]


def test_reconcile_refuses_to_drop_a_nonempty_wrong_key_table(tmp_path):
    con = duckdb.connect(str(tmp_path / "nonempty.duckdb"))
    con.execute(_LEGACY_DOSSIERS)
    con.execute("INSERT INTO dossiers (symbol, as_of) VALUES ('X', DATE '2026-01-01')")
    with pytest.raises(RuntimeError):
        init_schema(con)
    con.close()


def test_schema_and_upsert_replace(tmp_db):
    assert "prices_daily" in {r[0] for r in tmp_db.execute("SHOW TABLES").fetchall()}
    df = pd.DataFrame({"trade_date": [date(2026, 9, 11)] * 2, "symbol": ["A", "A"],
                       "series": ["EQ", "EQ"], "close": [10.0, 11.0]})
    n = upsert(tmp_db, "prices_daily", df)          # duplicate key collapses to last
    assert n == 1
    assert query(tmp_db, "SELECT close FROM prices_daily").iloc[0, 0] == 11.0
    upsert(tmp_db, "prices_daily", df.assign(close=[12.0, 13.0]))
    assert query(tmp_db, "SELECT count(*) FROM prices_daily").iloc[0, 0] == 1
    assert query(tmp_db, "SELECT close FROM prices_daily").iloc[0, 0] == 13.0


def test_runs(tmp_db):
    rid = new_run(tmp_db, "test")
    end_run(tmp_db, rid, "OK", "done")
    assert query(tmp_db, "SELECT status FROM runs WHERE run_id = ?", [rid]).iloc[0, 0] == "OK"


def test_statements_as_of_respects_visibility_and_basis(tmp_db):
    rows = [
        ("X", "standalone", "pl_q", date(2026, 6, 30), "sales", 100.0, date(2026, 8, 14)),
        ("X", "consolidated", "pl_q", date(2026, 6, 30), "sales", 120.0, date(2026, 8, 14)),
        ("X", "consolidated", "pl_q", date(2026, 3, 31), "sales", 90.0, date(2026, 5, 30)),
    ]
    df = pd.DataFrame(rows, columns=["symbol", "basis", "stmt", "period_end", "line_item", "value", "visible_from"])
    upsert(tmp_db, "statements", df)
    early = statements_as_of(tmp_db, date(2026, 8, 1), ["X"])
    assert list(early.period_end.dt.date) == [date(2026, 3, 31)]
    late = statements_as_of(tmp_db, date(2026, 8, 14), ["X"])
    assert len(late) == 2
    assert late[late.period_end.dt.date == date(2026, 6, 30)].value.iloc[0] == 120.0   # consolidated wins


def test_features_columns_exist(tmp_db):
    cols = table_columns(tmp_db, "features")
    for c in ("mom_12_1", "z_quality", "rankable", "altman_zpp"):
        assert c in cols
