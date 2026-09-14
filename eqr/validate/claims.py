"""Claim-state ladder. A passing acceptance bar is not a licence to say "validated": the
holdout was inspected, fundamentals are as-restated, market cap is not split-invariant, and the
benchmark is a proxy. Those verified integrity items hold a passing backtest at PROVISIONAL until
they are closed; only a sealed forward record promotes to PROSPECTIVE_VALIDATED.

    DIAGNOSTIC        bar failed, or the run was forced past a quality blocker, or no run exists
    PROVISIONAL       bar passed but >= 1 integrity item is still open
    BACKTEST_PASS     bar passed and every integrity item is closed
    PROSPECTIVE_VALIDATED   the forward ledger meets the live bar (never inferred from a backtest)
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Optional

import duckdb


class ClaimState(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    PROVISIONAL = "PROVISIONAL"
    BACKTEST_PASS = "BACKTEST_PASS"
    PROSPECTIVE_VALIDATED = "PROSPECTIVE_VALIDATED"


# The verified Codex P0/P1 items that change numbers or their meaning. resolved=False today.
OPEN_INTEGRITY_ITEMS = [
    {"code": "AS_RESTATED_FUNDAMENTALS", "resolved": False,
     "detail": "fundamentals are as-restated (first fetched 2026-09-14), not as-reported"},
    {"code": "MCAP_NOT_SPLIT_INVARIANT", "resolved": False,
     "detail": "market cap mixes current face value with historical raw close"},
    {"code": "HOLDOUT_INSPECTED", "resolved": False,
     "detail": "the holdout was inspected repeatedly during development"},
    {"code": "TRIALS_UNDERCOUNTED", "resolved": False,
     "detail": "deflated-Sharpe trial count historically excluded prior runs (now ledgered)"},
    {"code": "CONTROLS_NO_HISTORY", "resolved": False,
     "detail": "historical ASM/GSM/F&O exclusion state is absent"},
    {"code": "BENCH_PROXY", "resolved": False,
     "detail": "benchmark is a dividend-yield TR proxy, not the real NIFTY 500 TRI"},
]


def open_item_codes() -> list[str]:
    return [i["code"] for i in OPEN_INTEGRITY_ITEMS if not i["resolved"]]


def prospective_validated(con: duckdb.DuckDBPyConnection, sleeve: str, engine_version: Optional[str] = None,
                          min_matured: int = 100, min_months: int = 12) -> bool:
    """A minimal live-ledger gate (full M1–M5 land in Wave 3): >= min_matured matured rows spanning
    >= min_months distinct months with positive mean forward excess. Never reads a backtest row."""
    from .prospective import ENGINE_FOR_SLEEVE
    ev = engine_version or ENGINE_FOR_SLEEVE.get(sleeve, f"{sleeve}-v1")
    rows = con.execute("SELECT as_of, fwd_return, bench_return FROM prospective_ledger WHERE sleeve = ? AND "
                       "engine_version = ? AND outcome IN ('hit', 'miss') AND fwd_return IS NOT NULL",
                       [sleeve, ev]).fetchall()
    if len(rows) < min_matured:
        return False
    if len({(r[0].year, r[0].month) for r in rows}) < min_months:
        return False
    excess = [fr - (br or 0.0) for _, fr, br in rows]
    return sum(excess) / len(excess) > 0


def state_for(verdict: Optional[str], forced: bool, con: duckdb.DuckDBPyConnection,
              sleeve: str) -> tuple[ClaimState, list[str]]:
    if forced:
        return ClaimState.DIAGNOSTIC, ["run forced past a quality blocker"]
    if verdict != "VALIDATED":
        return ClaimState.DIAGNOSTIC, ["acceptance bar not passed" if verdict else "no validation run"]
    if prospective_validated(con, sleeve):
        return ClaimState.PROSPECTIVE_VALIDATED, []
    items = open_item_codes()
    return (ClaimState.PROVISIONAL, items) if items else (ClaimState.BACKTEST_PASS, [])


def claim_state(con: duckdb.DuckDBPyConnection, sleeve: str) -> tuple[ClaimState, list[str]]:
    """The current claim state for a sleeve, from its latest validation run + open integrity items."""
    row = con.execute("SELECT verdict, params FROM backtests WHERE sleeve = ? AND verdict IN "
                      "('VALIDATED', 'NOT VALIDATED') ORDER BY created_at DESC LIMIT 1", [sleeve]).fetchone()
    if not row:
        return ClaimState.DIAGNOSTIC, ["no validation run"]
    verdict, params = row
    forced = False
    try:
        forced = bool(json.loads(params or "{}").get("forced_reason"))
    except (TypeError, ValueError):
        forced = False
    return state_for(verdict, forced, con, sleeve)


def is_validated(state: ClaimState) -> bool:
    """Only these states earn the advisor's 'validated' flag / any edge points."""
    return state in (ClaimState.BACKTEST_PASS, ClaimState.PROSPECTIVE_VALIDATED)
