from datetime import date

from eqr.spine.universe import month_end_sessions
from eqr.validate import prospective as pr
from tests.conftest import make_synthetic_market


def _put_ranks(con, sleeve, as_of, held):
    for i, (s, w) in enumerate(held, 1):
        con.execute("INSERT INTO ranks (as_of, sleeve, symbol, rank, score, weight, regime, universe_size, detail) "
                    "VALUES (?, ?, ?, ?, 1.0, ?, 'RISK_ON', 40, 'base')", [as_of, sleeve, s, i, w])


def test_publish_is_gated_by_freeze_month_end_and_dedup(tmp_db):
    syms, days = make_synthetic_market(tmp_db, n_symbols=12, n_days=500)
    mes = month_end_sessions(tmp_db, days[100].date(), days[-1].date())
    me, held = mes[len(mes) // 2], [("S01", 0.3), ("S02", 0.3), ("S03", 0.4)]
    _put_ranks(tmp_db, "L", me, held)
    assert pr.publish(tmp_db, "L", "L-v1", as_of=me, freeze=date(2030, 1, 1))["published"] == 0   # before freeze
    _put_ranks(tmp_db, "L", days[101].date(), held)
    assert pr.publish(tmp_db, "L", "L-v1", as_of=days[101].date(), freeze=date(2000, 1, 1))["published"] == 0  # not month-end
    assert pr.publish(tmp_db, "L", "L-v1", as_of=me, freeze=date(2000, 1, 1))["published"] == 3
    assert pr.publish(tmp_db, "L", "L-v1", as_of=me, freeze=date(2000, 1, 1))["published"] == 0  # append-only dedup
    assert dict(tmp_db.execute("SELECT outcome, count(*) FROM prospective_ledger GROUP BY outcome").fetchall()) == {"pending": 3}


def test_score_fills_matured_rows_and_report_gates_on_min_matured(tmp_db):
    syms, days = make_synthetic_market(tmp_db, n_symbols=12, n_days=500)
    mes = month_end_sessions(tmp_db, days[100].date(), days[-1].date())
    me = mes[2]
    _put_ranks(tmp_db, "L", me, [("S01", 0.5), ("S02", 0.5)])
    pr.publish(tmp_db, "L", "L-v1", as_of=me, freeze=date(2000, 1, 1), horizon_days=20)
    assert pr.score(tmp_db, "L", as_of_max=me)["filled"] == 0          # horizon not elapsed
    assert pr.score(tmp_db, "L")["filled"] == 2                        # matured by the last session
    rows = tmp_db.execute("SELECT outcome, matured_at, fwd_return FROM prospective_ledger").fetchall()
    assert all(o in ("hit", "miss") and m is not None and f is not None for o, m, f in rows)
    assert pr.report(tmp_db, "L")["status"] == "INSUFFICIENT"          # < 100 matured
    out = pr.report(tmp_db, "L", min_matured=1)
    assert out["status"] == "OK" and "portfolio_excess" in out and 0.0 <= out["hit_rate"] <= 1.0
