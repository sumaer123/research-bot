"""Quality harness: cheap, deterministic checks that run after every refresh.
Failures are stored and surfaced; they never stop the refresh itself."""
from __future__ import annotations

from datetime import date, datetime

import duckdb

from ..store import insert_rows

REQUIRED_INDICES = ("Nifty 50", "Nifty 500", "India VIX")


def run_checks(con: duckdb.DuckDBPyConnection, run_id: str, as_of: date) -> list[dict]:
    out: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        out.append({"run_id": run_id, "as_of": as_of, "check_name": name,
                    "status": "PASS" if ok else "FAIL", "detail": detail, "checked_at": datetime.now()})

    n_eq = con.execute("SELECT count(*) FROM prices_daily WHERE trade_date = ? AND series = 'EQ'",
                       [as_of]).fetchone()[0]
    add("bhavcopy_eq_rows", 1500 <= n_eq <= 3000, f"{n_eq} EQ rows")

    dup = con.execute("""SELECT count(*) FROM (SELECT trade_date, symbol, series, count(*) c
                         FROM prices_daily WHERE trade_date = ? GROUP BY 1,2,3 HAVING c > 1)""",
                      [as_of]).fetchone()[0]
    add("no_duplicate_price_keys", dup == 0, f"{dup} duplicate keys")

    have = {r[0] for r in con.execute("SELECT index_name FROM index_daily WHERE trade_date = ?",
                                      [as_of]).fetchall()}
    missing = [i for i in REQUIRED_INDICES if i not in have]
    add("required_indices_present", not missing, f"missing {missing}" if missing else "all present")

    deliv = con.execute("""SELECT count(*) FILTER (WHERE deliv_pct IS NOT NULL) * 1.0 / nullif(count(*), 0)
                           FROM prices_daily WHERE trade_date = ? AND series = 'EQ'""", [as_of]).fetchone()[0]
    add("delivery_coverage", (deliv or 0) >= 0.9, f"{(deliv or 0) * 100:.1f}% of EQ rows")

    jumps = con.execute("""
        WITH px AS (SELECT symbol, trade_date, close,
                           lag(close) OVER (PARTITION BY symbol ORDER BY trade_date) AS prior
                    FROM prices_daily WHERE series = 'EQ' AND trade_date <= ?
                      AND trade_date >= (SELECT trade_date FROM trading_days WHERE trade_date <= ?
                                         ORDER BY trade_date DESC LIMIT 1 OFFSET 1))
        SELECT count(*) FROM px LEFT JOIN adj_factors a ON a.symbol = px.symbol AND a.ex_date = px.trade_date
        WHERE px.trade_date = ? AND prior > 0 AND abs(close / prior - 1) > 0.5 AND a.factor IS NULL
    """, [as_of, as_of, as_of]).fetchone()[0]
    add("unexplained_price_jumps", jumps == 0, f"{jumps} moves > 50% without an adjustment factor")

    stale = con.execute("""
        SELECT count(*) FROM universe_monthly u
        WHERE u.as_of = (SELECT max(as_of) FROM universe_monthly WHERE as_of <= ?)
          AND NOT EXISTS (SELECT 1 FROM statements s WHERE s.symbol = u.symbol
                          AND s.visible_from <= ? AND s.visible_from >= ? - INTERVAL 120 DAY)
    """, [as_of, as_of, as_of]).fetchone()[0]
    total = con.execute("SELECT count(*) FROM universe_monthly WHERE as_of = "
                        "(SELECT max(as_of) FROM universe_monthly WHERE as_of <= ?)", [as_of]).fetchone()[0]
    if total:
        add("statement_freshness", stale / total <= 0.3,
            f"{stale}/{total} universe names without a statement visible in the last 120 days")

    insert_rows(con, "quality_checks", out)
    return out
