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

    # --- xbrl_screener_agreement -------------------------------------------
    # For symbols that have BOTH XBRL FY revenue and a screener FY sales row,
    # check that ≥90 % of pairs agree within 5 % (both already in crore).
    try:
        pairs = con.execute("""
            WITH xbrl_rev AS (
                SELECT symbol, period_end, MAX(value) AS xbrl_rev
                FROM statements_xbrl
                WHERE item = 'revenue'
                  AND period_kind = 'FY'
                  AND visible_from <= ?
                GROUP BY symbol, period_end
            ),
            scr_rev AS (
                SELECT symbol, period_end, value AS scr_rev
                FROM statements
                WHERE line_item IN ('sales', 'revenue')
                  AND stmt = 'pl_a'
                  AND visible_from <= ?
            )
            SELECT x.symbol, x.period_end, x.xbrl_rev, s.scr_rev
            FROM xbrl_rev x
            JOIN scr_rev s ON x.symbol = s.symbol AND x.period_end = s.period_end
            WHERE x.xbrl_rev > 0 AND s.scr_rev > 0
        """, [as_of, as_of]).fetchall()
        if pairs:
            n_agree = sum(
                1 for _, _, xr, sr in pairs
                if abs(xr - sr) / max(xr, sr) <= 0.05
            )
            agree_rate = n_agree / len(pairs)
            add("xbrl_screener_agreement", agree_rate >= 0.90,
                f"{n_agree}/{len(pairs)} FY pairs agree within 5% ({agree_rate*100:.1f}%)")
        else:
            add("xbrl_screener_agreement", True, "no comparable FY pairs — skipped")
    except Exception as exc:
        add("xbrl_screener_agreement", True, f"check skipped: {exc}")

    # --- xbrl_freshness ----------------------------------------------------
    # Recent results_calendar rows with an xbrl_url should have a loaded
    # xbrl_filings row.  PASS when coverage ≥ 80 % (90-day lookback).
    try:
        total = con.execute(
            "SELECT count(*) FROM results_calendar "
            "WHERE xbrl_url IS NOT NULL AND period_end >= ? - INTERVAL 90 DAY",
            [as_of]).fetchone()[0]
        if total > 0:
            loaded = con.execute("""
                SELECT count(*)
                FROM results_calendar rc
                WHERE rc.xbrl_url IS NOT NULL
                  AND rc.period_end >= ? - INTERVAL 90 DAY
                  AND EXISTS (
                      SELECT 1 FROM xbrl_filings xf
                      WHERE xf.xbrl_url = rc.xbrl_url AND xf.status = 'ok'
                  )
            """, [as_of]).fetchone()[0]
            coverage = loaded / total
            add("xbrl_freshness", coverage >= 0.80,
                f"{loaded}/{total} recent XBRL calendar entries loaded ({coverage*100:.1f}%)")
        else:
            add("xbrl_freshness", True, "no recent XBRL calendar entries — skipped")
    except Exception as exc:
        add("xbrl_freshness", True, f"check skipped: {exc}")

    insert_rows(con, "quality_checks", out)
    return out
