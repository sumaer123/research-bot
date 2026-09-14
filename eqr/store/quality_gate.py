"""Quality gate: refuse backtest / validate / rank when the latest data-quality run on or
before the as-of date left an unresolved BLOCKER. A caller may proceed with an explicit
--force reason, which is recorded and marks the run non-validatable (claim state DIAGNOSTIC)."""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

import duckdb

from ..spine.quality import severity


class QualityBlocked(RuntimeError):
    """Raised when a gated operation hits an unresolved BLOCKER and no force reason was given."""


def latest_blockers(con: duckdb.DuckDBPyConnection, as_of: date) -> list[dict]:
    """Failing BLOCKER checks from the most recent quality run whose as_of <= the given date."""
    row = con.execute("SELECT run_id FROM quality_checks WHERE as_of <= ? "
                      "GROUP BY run_id ORDER BY max(checked_at) DESC LIMIT 1", [as_of]).fetchone()
    if not row:
        return []
    rows = con.execute("SELECT check_name, status, detail FROM quality_checks WHERE run_id = ?", [row[0]]).fetchall()
    return [{"check": c, "detail": d} for c, s, d in rows if s == "FAIL" and severity(c) == "BLOCKER"]


def assert_quality(con: duckdb.DuckDBPyConnection, as_of: date, purpose: str,
                   force_reason: Optional[str] = None) -> dict:
    blockers = latest_blockers(con, as_of)
    if not blockers:
        return {"ok": True, "forced": False, "forced_reason": None, "blockers": []}
    if force_reason:
        return {"ok": True, "forced": True, "forced_reason": force_reason, "blockers": blockers}
    names = ", ".join(b["check"] for b in blockers)
    raise QualityBlocked(f"{purpose} refused: unresolved quality BLOCKER(s): {names}. "
                         f"Fix the data or re-run with --force \"reason\" (marks the run non-validatable).")


def record_forced(con: duckdb.DuckDBPyConnection, run_id: str, reason: str) -> None:
    """Stamp forced_reason into a backtests row's params JSON so the claim-state ladder treats it
    as DIAGNOSTIC. No-op when the run_id is absent (e.g. `eqr rank`, which has no backtests row)."""
    row = con.execute("SELECT params FROM backtests WHERE run_id = ?", [run_id]).fetchone()
    if not row:
        return
    try:
        params = json.loads(row[0]) if row[0] else {}
    except (TypeError, ValueError):
        params = {}
    params["forced_reason"] = reason
    con.execute("UPDATE backtests SET params = ? WHERE run_id = ?", [json.dumps(params, default=str), run_id])
