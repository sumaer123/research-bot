"""Graphify code-graph integration: in-process reader + `eqr graph` CLI.

Anchored on the committed graphify-out/graph.json (built @ fdca0ebe):
994 nodes · 2357 edges · 51 communities. god node #1 is upsert() (32).
"""
import time

import pytest
from typer.testing import CliRunner

from eqr.spine.graph import GraphifyReader, graph_path
from eqr.cli import app

runner = CliRunner()


@pytest.fixture()
def reader():
    return GraphifyReader()


def test_stats_are_self_consistent(reader):
    # node/edge/community counts are build artifacts that grow with the tree —
    # assert consistency with the underlying JSON + sane floors, never a frozen total.
    s = reader.stats
    assert s["nodes"] == len(reader._g["nodes"])
    assert s["edges"] == len(reader._g["links"])
    assert s["nodes"] >= 900 and s["edges"] > s["nodes"] and s["communities"] >= 40
    assert isinstance(s["built_at_commit"], str) and len(s["built_at_commit"]) >= 7


def test_resolve_symbol_and_file(reader):
    assert reader.resolve("rank_sleeve") == ["eqr_strategy_rank_rank_sleeve"]
    assert reader.resolve("rank_sleeve()") == ["eqr_strategy_rank_rank_sleeve"]
    assert reader.resolve("eqr/strategy/rank.py")          # file query -> non-empty
    assert reader.resolve("no_such_symbol_xyz") == []


def test_neighbors_include_known_edges(reader):
    nbs = reader.neighbors("eqr_strategy_rank_rank_sleeve")
    # imported/called by cli.py (an in-edge whose other end lives in eqr/cli.py)
    assert any(n.direction == "in" and n.source_file == "eqr/cli.py" for n in nbs)
    # calls score() / select() / publish() (out-edges, relation "calls")
    called = {n.label for n in nbs if n.direction == "out" and n.relation == "calls"}
    assert {"score()", "select()", "publish()"} <= called


def test_god_nodes_top_is_upsert(reader):
    top = reader.god_nodes(3)
    assert top[0] == ("upsert()", 32)
    labels = [lbl for lbl, _ in top]
    assert "load_parsed_xbrl()" in labels                  # #2, 31 edges


def test_communities_are_structurally_sound(reader):
    # Community *names* depend on whether the LLM labeling step ran (a hook rebuild
    # without a backend degrades them to hub-node placeholders) — assert structure only.
    c = reader.communities()
    assert len(c) >= 40
    assert all(isinstance(k, str) and isinstance(v, int) for k, v in c.items())
    assert sum(c.values()) == sum(1 for n in reader._g["nodes"] if n.get("community") is not None)


def test_missing_graph_raises_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setenv("EQR_GRAPH_PATH", str(tmp_path / "nope.json"))
    r = GraphifyReader()
    with pytest.raises(FileNotFoundError, match="eqr graph rebuild"):
        _ = r.stats


def test_env_override_changes_graph_path(tmp_path, monkeypatch):
    monkeypatch.setenv("EQR_GRAPH_PATH", str(tmp_path / "g.json"))
    assert graph_path() == (tmp_path / "g.json").resolve()


def test_markdown_snippet_is_grouped_by_relation(reader):
    md = reader.as_markdown("rank_sleeve")
    assert "rank_sleeve()" in md and "eqr/strategy/rank.py" in md
    assert "→ calls" in md and "· community _" in md          # label text is not a stable anchor
    assert reader.as_markdown("no_such_symbol_xyz").startswith("_No node")


def test_neighbor_lookup_under_50ms(reader):
    reader.stats                                            # warm the one-time JSON parse
    t0 = time.perf_counter()
    for _ in range(100):
        reader.neighbors("eqr_strategy_rank_rank_sleeve")
    assert (time.perf_counter() - t0) / 100 < 0.05


# ---- CLI smoke -----------------------------------------------------------

def test_graph_status_cli(reader, monkeypatch):
    monkeypatch.setattr("eqr.spine.graph.GraphifyReader.is_stale", lambda self: False)
    res = runner.invoke(app, ["graph", "status"])
    assert res.exit_code == 0
    assert f"{reader.stats['nodes']} nodes" in res.stdout and "FRESH" in res.stdout


def test_graph_query_cli_names_the_file():
    res = runner.invoke(app, ["graph", "query", "rank_sleeve"])
    assert res.exit_code == 0 and "eqr/strategy/rank.py" in res.stdout


def test_graph_hubs_cli():
    res = runner.invoke(app, ["graph", "hubs", "--top", "5"])
    assert res.exit_code == 0 and "upsert()" in res.stdout


def test_no_data_or_secret_nodes_in_graph(reader):
    """Regression tripwire: .graphifyignore must keep data/ and secrets out of the graph."""
    bad = [n["source_file"] for n in reader._g["nodes"]
           if n.get("source_file", "").startswith("data/")
           or n.get("source_file", "").endswith((".duckdb", ".db", ".sqlite"))
           or "token" in n.get("source_file", "").lower()
           or ".env" in n.get("source_file", "")]
    assert bad == []
