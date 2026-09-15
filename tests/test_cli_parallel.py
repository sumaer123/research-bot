"""T10: CLI surface — `webresearch`, `dossier --no-web`, `parallel status`, and the `_parallel_status`
helper the doctor line uses. No network: the network-touching bits are monkeypatched, and the DB is a
throwaway file the CLI opens itself (so we don't hold a competing DuckDB writer)."""
import json

import pytest
from typer.testing import CliRunner

import eqr.research.dossier as dossier_mod
import eqr.research.parallel_client as pc
import eqr.research.webresearch as wr
from eqr.cli import app, _parallel_status, _parallel_lines

runner = CliRunner()


@pytest.fixture()
def dbenv(tmp_path, monkeypatch):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EQR_PARALLEL_ENABLED", "1")
    from eqr.store import connect
    connect(tmp_path / "data" / "eqr.duckdb").close()          # create schema, release the writer
    return tmp_path


def test_webresearch_command_prints_one_line_per_symbol_and_exits_0_on_partial(dbenv, monkeypatch):
    def fake(con, symbol, as_of=None, **kw):
        return {"status": "PARTIAL" if symbol == "AAA" else "OK", "run_id": "r", "expected": 3,
                "received": 2, "sources": 1, "calls": 4, "path": "x"}
    monkeypatch.setattr(wr, "run_webresearch", fake)
    res = runner.invoke(app, ["webresearch", "AAA", "BBB"])
    assert res.exit_code == 0
    lines = [json.loads(l) for l in res.stdout.strip().splitlines() if l.strip().startswith("{")]
    assert len(lines) == 2 and lines[0]["status"] == "PARTIAL"


def test_dossier_no_web_flag_threads_through(dbenv, monkeypatch):
    seen = {}

    def fake(con, symbol, as_of=None, model=None, dry_run=False, web=True):
        seen["web"] = web
        return {"status": "STORED", "run_id": "r", "rating": "BUY", "confidence": 0.6, "path": "x",
                "web_claims": 0, "struck": 0, "webresearch": None}
    monkeypatch.setattr(dossier_mod, "run_dossier", fake)
    assert runner.invoke(app, ["dossier", "S05", "--no-web"]).exit_code == 0
    assert seen["web"] is False
    runner.invoke(app, ["dossier", "S05"])
    assert seen["web"] is True                                # web on by default


def test_parallel_status_command_prints_mcp_and_balance(dbenv, monkeypatch):
    monkeypatch.setattr(pc.McpClient, "initialize", lambda self: True)
    monkeypatch.setattr(pc, "cli_path", lambda: "/usr/local/bin/parallel-cli")
    monkeypatch.setattr(pc, "cli_balance_usd", lambda: 19.86)
    res = runner.invoke(app, ["parallel", "status"])
    assert res.exit_code == 0
    assert "parallel_mcp" in res.stdout and "ok" in res.stdout
    assert "$19.86" in res.stdout and "WARN" not in res.stdout


def test_parallel_status_warns_when_credit_moved(dbenv, monkeypatch):
    monkeypatch.setattr(pc.McpClient, "initialize", lambda self: False)
    monkeypatch.setattr(pc, "cli_path", lambda: None)
    monkeypatch.setattr(pc, "cli_balance_usd", lambda: 5.00)
    res = runner.invoke(app, ["parallel", "status"])
    assert res.exit_code == 0
    assert "fail" in res.stdout and "WARN" in res.stdout and "$5.00" in res.stdout


def test_parallel_status_helper_counts_runs(tmp_db, monkeypatch):
    # tmp_db disables parallel; force the reachability probe to a known value
    monkeypatch.setattr(pc.McpClient, "initialize", lambda self: True)
    monkeypatch.setattr(pc, "cli_balance_usd", lambda: 19.86)
    from datetime import datetime
    tmp_db.execute("INSERT INTO research_runs (run_id, symbol, mode, status, started_at) VALUES "
                   "('a','S05','webresearch','OK',?), ('b','S05','dossier_web','STORED',?)",
                   [datetime.now(), datetime.now()])
    st = _parallel_status(tmp_db)
    assert st["webresearch_7d"] == 1 and st["dossier_web_7d"] == 1 and st["mcp_ok"] is True
    lines = _parallel_lines(st)
    assert any("parallel_mcp" in ln for ln in lines) and any("dossier_web 1" in ln for ln in lines)
