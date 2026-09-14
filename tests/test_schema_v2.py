"""Tests for Phase-1 schema additions and migrations (T1.1)."""
import duckdb
import pytest

from eqr.store.db import init_schema, table_columns

# All 21 tables added by Phase-1 DDL appended to schema.sql
_ALL_NEW_TABLES = [
    "statements_xbrl",
    "statements_xbrl_revisions",
    "xbrl_filings",
    "credit_ratings",
    "board_meetings",
    "insider_trades",
    "holders_named",
    "pledges",
    "doc_sections",
    "fund_metrics",
    "graph_nodes",
    "graph_edges",
    "graph_aliases",
    "graph_features",
    "ratings",
    "rating_ledger",
    "rating_calibrations",
    "research_runs",
    "dossier_claims",
    "web_sources",
    "news_items",
]

# Tables whose DDL declares BOTH as_of AND visible_from (built from the verbatim DDL)
_BOTH_PIT_COLS = [
    "statements_xbrl",
    "credit_ratings",
    "board_meetings",
    "insider_trades",
    "holders_named",
    "pledges",
    "graph_edges",
    "web_sources",
    "news_items",
]


def test_schema_v2_tables_and_migrations_are_idempotent(tmp_db):
    """Fresh init creates all new tables; second init is a no-op; migration columns present."""
    existing = {r[0] for r in tmp_db.execute("SHOW TABLES").fetchall()}
    for t in _ALL_NEW_TABLES:
        assert t in existing, f"table {t!r} missing after first init_schema"

    # Second call must not raise and must leave table set intact
    init_schema(tmp_db)
    existing2 = {r[0] for r in tmp_db.execute("SHOW TABLES").fetchall()}
    for t in _ALL_NEW_TABLES:
        assert t in existing2, f"table {t!r} missing after second init_schema"

    # Migration columns on results_calendar
    rc_cols = table_columns(tmp_db, "results_calendar")
    for col in ("xbrl_url", "seq_id", "type_sub"):
        assert col in rc_cols, f"results_calendar missing migration column {col!r}"

    # Migration column on documents
    doc_cols = table_columns(tmp_db, "documents")
    assert "extract_status" in doc_cols, "documents missing migration column 'extract_status'"

    # Migration columns on dossiers
    dos_cols = table_columns(tmp_db, "dossiers")
    for col in ("schema_version", "engine_rating", "llm_view", "run_id"):
        assert col in dos_cols, f"dossiers missing migration column {col!r}"


def test_new_tables_carry_as_of_and_visible_from(tmp_db):
    """Tables whose DDL declares both as_of and visible_from must have both columns."""
    for t in _BOTH_PIT_COLS:
        cols = table_columns(tmp_db, t)
        assert "as_of" in cols, f"{t!r} missing 'as_of'"
        assert "visible_from" in cols, f"{t!r} missing 'visible_from'"
