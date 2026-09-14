from datetime import date

import pandas as pd

from eqr.store import upsert, query, new_run, end_run, table_columns
from eqr.store.pit import statements_as_of


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
