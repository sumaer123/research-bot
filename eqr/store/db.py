"""DuckDB store: one file, idempotent schema, key-based upserts.

DuckDB is single-writer. Refresh jobs open a writer; the web app opens read-only
connections per request and reports 503 when a writer holds the file.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from ..config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_PATH = Path(__file__).with_name("migrations.sql")


def connect(path: Optional[Path] = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    p = Path(path) if path else settings().db_path
    p.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(p), read_only=read_only)
    if not read_only:
        init_schema(con)
    return con


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_PATH.read_text())
    con.execute(MIGRATIONS_PATH.read_text())


def table_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
        "ORDER BY ordinal_position", [table]).fetchall()
    return [r[0] for r in rows]


def upsert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """INSERT OR REPLACE the DataFrame's columns (subset allowed; missing -> NULL).

    Rows with duplicate primary keys inside `df` are collapsed to the last one so a
    single statement never trips DuckDB's same-batch conflict rule."""
    if df is None or df.empty:
        return 0
    cols = table_columns(con, table)
    if not cols:
        raise ValueError(f"unknown table {table}")
    present = [c for c in cols if c in df.columns]
    if not present:
        raise ValueError(f"no matching columns for {table}: {list(df.columns)}")
    pk = _primary_key(con, table)
    frame = df[present].copy()
    if pk and all(k in frame.columns for k in pk):
        frame = frame.drop_duplicates(subset=pk, keep="last")
    con.register("_eqr_upsert", frame)
    col_sql = ", ".join(f'"{c}"' for c in present)
    con.execute(f'INSERT OR REPLACE INTO "{table}" ({col_sql}) SELECT {col_sql} FROM _eqr_upsert')
    con.unregister("_eqr_upsert")
    return len(frame)


def _primary_key(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    rows = con.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'", [table]).fetchall()
    return list(rows[0][0]) if rows else []


def query(con: duckdb.DuckDBPyConnection, sql: str, params: Optional[list] = None) -> pd.DataFrame:
    return con.execute(sql, params or []).df()


def new_run(con: duckdb.DuckDBPyConnection, kind: str, detail: str = "") -> str:
    run_id = f"{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    con.execute("INSERT INTO runs VALUES (?, ?, ?, NULL, 'RUNNING', ?)",
                [run_id, kind, datetime.now(), detail])
    return run_id


def end_run(con: duckdb.DuckDBPyConnection, run_id: str, status: str, detail: str = "") -> None:
    con.execute("UPDATE runs SET ended_at = ?, status = ?, detail = ? WHERE run_id = ?",
                [datetime.now(), status, detail, run_id])


def insert_rows(con: duckdb.DuckDBPyConnection, table: str, rows: list[dict]) -> int:
    """Plain INSERT (no key semantics) for log-style tables."""
    if not rows:
        return 0
    cols = table_columns(con, table)
    df = pd.DataFrame(rows)
    present = [c for c in cols if c in df.columns]
    con.register("_eqr_insert", df[present])
    col_sql = ", ".join(f'"{c}"' for c in present)
    con.execute(f'INSERT INTO "{table}" ({col_sql}) SELECT {col_sql} FROM _eqr_insert')
    con.unregister("_eqr_insert")
    return len(df)
