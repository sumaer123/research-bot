# 🕸️ Project Research Bot: Graphify Integration Implementation Plan

> **Status:** Design/implementation plan — no source edits performed. TDD required for every code item (test-first, watch it fail, then implement).
> **Repo root:** `/Users/sumaer.bahl/Downloads/Sumaer's Claude Data/Project Research Bot`
> **Graph built from commit:** `fdca0ebe` (`built_at_commit: fdca0ebee9c5d4c69afda6463cb8c2a29aedb8a0`)
> **All paths below are repo-relative** (matching the graph's own `source_file` convention, e.g. `eqr/strategy/rank.py`).

---

## 1. Executive Summary & Graph Topology Overview

Project Research Bot (`eqr`) has a **prebuilt, git-synced Graphify code graph** in `graphify-out/`. This plan makes that graph **first-class inside the app and the developer/agent workflow** — queryable from the `eqr` CLI, readable in-process by a small helper module, and documented for humans and subagents — **without duplicating what the `graphify` binary already does well** and **without touching numbers, data, or the DuckDB store.**

### Verified graph facts (from `graphify-out/`)

| Fact | Value | Source |
|---|---|---|
| Nodes | **994** | `graph.json` `nodes[]`, `GRAPH_REPORT.md` |
| Structural edges | **2,357** | `graph.json` `links[]` |
| Communities | **51** (45 shown, 6 thin omitted) | `.graphify_labels.json` (ids 0–50) |
| Extraction confidence | 99% EXTRACTED · 1% INFERRED (26 edges) | `GRAPH_REPORT.md` |
| Directed / multigraph | `false` / `false` | `graph.json` top-level flags |
| Hyperedges | `0` | `graph.json` `hyperedges[]` |
| `graphify` CLI | installed at `/Users/sumaer.bahl/.local/bin/graphify` | `command -v graphify` |
| Git hooks | `post-commit`, `post-checkout` (both executable, present) | `.git/hooks/` |

**Node record shape** (real example, `rank_sleeve()`):
```json
{"label": "rank_sleeve()", "file_type": "code", "source_file": "eqr/strategy/rank.py",
 "source_location": "L16", "_callable": true, "_origin": "ast", "community": 8,
 "norm_label": "rank_sleeve()", "id": "eqr_strategy_rank_rank_sleeve",
 "community_name": "Sleeve Ranking & Regime"}
```
**Node ID scheme:** dotted module path with separators collapsed to `_`, plus symbol — `eqr/strategy/rank.py::rank_sleeve` → `eqr_strategy_rank_rank_sleeve`; a file node is `eqr_cli`, `deploy_backup`, etc.

**Link record shape** (real example):
```json
{"relation": "calls", "confidence": "EXTRACTED", "confidence_score": 1.0, "weight": 1.0,
 "source": "eqr_cli_rank", "target": "eqr_strategy_rank_rank_sleeve",
 "source_file": "eqr/cli.py", "source_location": "L246", "_origin": "ast"}
```
**Relation histogram** (all 2,357 edges): `calls` 777 · `contains` 608 · `references` 333 · `imports` 253 · `rationale_for` 160 · `imports_from` 134 · `extends` 35 · `method` 27 · `indirect_call` 14 · `uses` 9 · `inherits` 5 · `re_exports` 1 · `reads_from` 1.

### Key functional hubs relevant to research work

The graph's 51 communities map cleanly onto the research pipeline. The ones agents touch most when extending fundamentals/strategy:

| Community | Name (`.graphify_labels.json`) | Primary files |
|---|---|---|
| 8 | **Sleeve Ranking & Regime** | `eqr/strategy/rank.py`, `eqr/strategy/sleeves.py`, `eqr/strategy/regime.py` |
| 9 | **Feature Building Pipeline** | `eqr/features/build.py`, `eqr/features/panel.py` |
| 11 | **Fundamental Features** | `eqr/features/fundamental.py` (`_piotroski`, `_altman`, …) |
| 39 | **Price Features** | `eqr/features/price.py` |
| 3 | **Claude Dossier Runner** | `eqr/research/dossier.py` (`_binding_errors`, `_prompt`, `_call_claude`) |
| 1 | **NSE Document Ingestion** | `eqr/research/docstore.py` |
| 19/21/24/26–29/33–36 | **Dossier/Claim JSON-Schema** communities | `eqr/research/schema.py`, `eqr/research/schema.json` |
| 10 | **DuckDB Store Layer** | `eqr/store/db.py` (`upsert`, `init_schema`) |
| 4 | **Database Schema Tables** | `eqr/store/schema.sql` tables |
| 16 | **Quality Gate & Checks** | `eqr/store/quality_gate.py`, `eqr/spine/quality.py` |
| 13 / 14 | **Trial Ledger** / **Prospective Forward Ledger** | `eqr/validate/trials.py`, `eqr/validate/prospective.py` |
| 20 / 23 / 17 | **Backtest Engine** / **Acceptance & Walk-Forward** / **Performance Metrics** | `eqr/validate/backtest.py`, `walkforward.py`, `costs.py` |

**God nodes (most-connected — the true core abstractions):**
`upsert()` (32) · `load_parsed_xbrl()` (31) · `refresh_factors()` (29) · `connect()` (28) · `run_backtest()` (28) · `build_features()` (27) · `make_synthetic_market()` (25) · `Http` (23) · `NseApi` (23) · `parse_xbrl()` (23) · `run_walk_forward()` (22) · `SleeveConfig` (20).

**Design consequence:** `connect()`, `upsert()`, and `build_features()` are cross-community bridges (high betweenness). Any change to them has wide blast radius — the graph is exactly the tool to measure that before editing, which is the core value this integration delivers.

---

## 2. CLI & Runtime Integration Design (`eqr graph`)

### 2.1 Design principle — wrap, don't reimplement

The `graphify` binary already ships `query`, `explain`, `affected`, `path`, `god-nodes`, and `update`. The `eqr graph` group should therefore be a **thin, in-process, dependency-light surface** that:

- serves the **90% agent case** (`status`, `query`, `hubs`) by reading `graphify-out/graph.json` **in-process** via `GraphifyReader` (§3) — **no subprocess, no PATH dependency, <50 ms**;
- delegates **re-extraction** (`rebuild`) to the `graphify` binary, because rebuilding is graphify's job and requires its AST extractor;
- exposes richer traversals (`explain`, `path`) by shelling out to `graphify` **only when the binary is present**, degrading to the in-process neighbor view otherwise.

This keeps `eqr` importable and testable without the `graphify` package installed, and avoids maintaining a second BFS implementation.

### 2.2 Command surface

Registered as a Typer sub-app: `app.add_typer(graph_app, name="graph")` in `eqr/cli.py`.

| Command | Behaviour | Backing |
|---|---|---|
| `eqr graph status` | Node/edge/community counts, `built_at_commit`, `graph.json` mtime, **staleness** (compare to `git rev-parse HEAD`), git-hook install state. | `GraphifyReader` + `git` |
| `eqr graph query "<target>"` | Resolve a symbol/file to its node, print its **direct neighbors grouped by relation** and its **community hub**. `--depth N` (default 1) expands. `--json` for machine output. | `GraphifyReader.neighbors()` |
| `eqr graph hubs` | List community hubs (name + node count) and top god-nodes. `--top N`. | `GraphifyReader.communities()` / `.god_nodes()` |
| `eqr graph explain "<symbol>"` | Rich plain-language node explanation. Shells to `graphify explain`; falls back to `query`. | `graphify` bin / reader |
| `eqr graph rebuild` | Runs `graphify update .` (re-extract, re-cluster). `--no-cluster` passthrough. Refuses if `graphify` not on PATH, with the exact install hint. | subprocess `graphify` |

### 2.3 Usage examples (real nodes)

```bash
# What does the ranker touch, and what breaks if I change it?
eqr graph query "rank_sleeve"
#   NODE rank_sleeve()  [eqr/strategy/rank.py:L16 · community "Sleeve Ranking & Regime"]
#   <-- called by:  rank() (eqr/cli.py:L246), _prep() (tests/test_surfaces.py:L23)
#   --> calls:      score(), select(), publish(), regime_at(), inverse_vol_weights(), rank_table()
#   --> references: SleeveConfig, DuckDBPyConnection

# Is my graph fresh?
eqr graph status
#   994 nodes · 2357 edges · 51 communities
#   built_at_commit fdca0ebe · HEAD fdca0ebe  →  FRESH
#   post-commit hook: installed · post-checkout hook: installed

# Where are the architectural hubs before I refactor?
eqr graph hubs --top 8

# After editing code, refresh the graph on demand:
eqr graph rebuild        # → graphify update .
```

`eqr graph query`/`status`/`hubs` must **never import the `graphify` package** — they read the JSON directly, so they work in CI and on a box where only the artifacts (not the tool) exist.

---

## 3. Python Module Architecture (`eqr/spine/graph.py`)

New module, no third-party deps (stdlib `json`, `functools`, `subprocess`, `pathlib` + existing `eqr.config`). Path resolution follows the existing `Settings` pattern: add an `EQR_GRAPH_PATH` env override defaulting to `<PROJECT_ROOT>/graphify-out/graph.json`.

### 3.1 `GraphifyReader` — in-process query engine

```python
"""In-process reader for the Graphify code graph (graphify-out/graph.json).
Zero third-party deps: works wherever the artifacts exist, even without the
graphify package installed. Designed for <50ms neighbor lookups."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Optional

from .config import PROJECT_ROOT  # reuse the app's absolute-path convention


def graph_path() -> Path:
    import os
    p = os.environ.get("EQR_GRAPH_PATH")
    return Path(p).expanduser().resolve() if p else PROJECT_ROOT / "graphify-out" / "graph.json"


@dataclass(frozen=True)
class Neighbor:
    node_id: str
    label: str
    relation: str
    direction: str          # "out" (this -> other) or "in" (other -> this)
    source_file: str
    source_location: str


class GraphifyReader:
    """Loads graph.json once and answers neighbor / hub / staleness questions."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or graph_path()

    @cached_property
    def _g(self) -> dict:
        if not self.path.exists():
            raise FileNotFoundError(
                f"no code graph at {self.path} — run `eqr graph rebuild` (or `graphify update .`)")
        return json.loads(self.path.read_text())

    @cached_property
    def _nodes(self) -> dict[str, dict]:
        return {n["id"]: n for n in self._g["nodes"]}

    @cached_property
    def _by_label(self) -> dict[str, list[str]]:
        idx: dict[str, list[str]] = {}
        for n in self._g["nodes"]:
            for key in {n["label"], n.get("norm_label", n["label"]), n["id"]}:
                idx.setdefault(key.lower(), []).append(n["id"])
        return idx

    # ---- stats -----------------------------------------------------------
    @property
    def stats(self) -> dict:
        g = self._g
        return {
            "nodes": len(g["nodes"]),
            "edges": len(g["links"]),
            "communities": len({n.get("community") for n in g["nodes"] if n.get("community") is not None}),
            "built_at_commit": g.get("built_at_commit"),
            "graph_mtime": self.path.stat().st_mtime,
        }

    def is_stale(self) -> Optional[bool]:
        """True if HEAD != built_at_commit. None if HEAD can't be resolved."""
        built = (self._g.get("built_at_commit") or "")[:8]
        if not built:
            return None
        try:
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                                  capture_output=True, text=True, timeout=5).stdout.strip()[:8]
        except Exception:
            return None
        return bool(head) and head != built

    # ---- resolution & traversal -----------------------------------------
    def resolve(self, target: str) -> list[str]:
        """target may be a node id, a label ('rank_sleeve' / 'rank_sleeve()'),
        or a source_file ('eqr/strategy/rank.py'). Returns matching node ids."""
        t = target.lower()
        hits = self._by_label.get(t) or self._by_label.get(t + "()")
        if hits:
            return hits
        return [n["id"] for n in self._g["nodes"] if n.get("source_file", "").lower() == t]

    def neighbors(self, node_id: str) -> list[Neighbor]:
        out: list[Neighbor] = []
        for l in self._g["links"]:
            if l["source"] == node_id:
                other = self._nodes.get(l["target"], {})
                out.append(Neighbor(l["target"], other.get("label", l["target"]), l["relation"],
                                    "out", other.get("source_file", ""), other.get("source_location", "")))
            elif l["target"] == node_id:
                other = self._nodes.get(l["source"], {})
                out.append(Neighbor(l["source"], other.get("label", l["source"]), l["relation"],
                                    "in", other.get("source_file", ""), other.get("source_location", "")))
        return out

    def god_nodes(self, top: int = 10) -> list[tuple[str, int]]:
        deg: dict[str, int] = {}
        for l in self._g["links"]:
            deg[l["source"]] = deg.get(l["source"], 0) + 1
            deg[l["target"]] = deg.get(l["target"], 0) + 1
        ranked = sorted(deg.items(), key=lambda kv: kv[1], reverse=True)
        return [(self._nodes.get(nid, {}).get("label", nid), d) for nid, d in ranked[:top]]

    def communities(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self._g["nodes"]:
            name = n.get("community_name", f"Community {n.get('community')}")
            counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    # ---- LLM-context rendering ------------------------------------------
    def as_markdown(self, target: str, depth: int = 1) -> str:
        """Compact Markdown snippet for an LLM context window."""
        ids = self.resolve(target)
        if not ids:
            return f"_No node matching `{target}` in the code graph._"
        lines: list[str] = []
        for nid in ids[:5]:
            n = self._nodes[nid]
            lines.append(f"### `{n['label']}` — {n['source_file']}:{n['source_location']} "
                         f"· community _{n.get('community_name')}_")
            grouped: dict[str, list[str]] = {}
            for nb in self.neighbors(nid):
                arrow = "→" if nb.direction == "out" else "←"
                grouped.setdefault(f"{arrow} {nb.relation}", []).append(
                    f"`{nb.label}` ({nb.source_file}:{nb.source_location})")
            for rel, items in sorted(grouped.items()):
                lines.append(f"- **{rel}**: " + ", ".join(items[:12]))
        return "\n".join(lines)
```

### 3.2 `rebuild()` delegation helper (same module)

```python
def rebuild(no_cluster: bool = False) -> int:
    """Delegate re-extraction to the graphify binary. Returns its exit code."""
    import shutil
    exe = shutil.which("graphify")
    if not exe:
        raise RuntimeError("graphify not on PATH — install with `graphify install` "
                           "or run the rebuild from a shell that has it.")
    cmd = [exe, "update", str(PROJECT_ROOT)] + (["--no-cluster"] if no_cluster else [])
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode
```

**Why this shape:** mirrors the app's existing conventions — frozen dataclasses, `PROJECT_ROOT`-anchored paths, `shutil.which(...)` fallback (the exact pattern `eqr/research/dossier.py` already uses to find the `claude` CLI). `cached_property` guarantees the ~1.1 MB JSON is parsed once per process.

---

## 4. Agentic Workflow & Codebase Context Optimization

### 4.1 The rule for AI agents working on `eqr`

> **Query the graph before you grep.** A `UserPromptSubmit` hook already nudges this (`graphify-first`). Formalize it: before any Read/Grep sweep to locate code, run **one** graph query, then Read **only** the returned `source_file:source_location` — never whole directories.

Concrete agent recipe (all commands verified against this repo):

```bash
graphify query "<feature you're about to touch>"   # files + line numbers + blast radius
graphify affected "eqr/research/schema.py"          # reverse deps: what breaks if I change X
graphify explain "rank_sleeve"                       # one node + its neighbors in prose
graphify path "dossier()" "upsert()"                 # how two symbols connect
```

Worked example — an agent asked to add a fundamental factor:
1. `graphify query "fundamental features"` → lands on `eqr/features/fundamental.py` (community 11: `_piotroski`, `_altman`, `fundamental_features`).
2. `graphify affected "eqr/features/fundamental.py"` → shows `build_features()` (community 9) and downstream `rank_sleeve()` consume it — so the change's blast radius reaches Sleeve Ranking.
3. Read only those files. Change the factor. Then `eqr graph rebuild` (or let the post-commit hook do it).

### 4.2 Prompt template for feeding community hubs into subagents

When dispatching a subagent to work on a subsystem, prepend graph context instead of raw file dumps:

```
You are editing the {COMMUNITY_NAME} subsystem of the eqr research engine.
Graph-derived context (from graphify-out/graph.json @ {BUILT_AT_COMMIT}):

Files in this community:
{list of source_file for nodes where community_name == COMMUNITY_NAME}

Cross-community bridges you must NOT break (high blast radius):
{god_nodes touching this community, e.g. connect(), upsert(), build_features()}

Direct dependents (reverse edges) of the symbol you will change:
{output of GraphifyReader.as_markdown(TARGET)}

Rule: Read only the files/lines cited above. If you need more, run
`graphify query "<narrower question>"` — do not sweep directories.
```

### 4.3 `docs/GRAPHIFY_GUIDE.md` (specification of what it must contain)

A developer/agent guide living beside the other project docs. **Authoring/committing this `.md` is the `documentation-engineer`'s job** (per the standing docs rule) — this plan specifies its required contents, it does not hand-write it:

1. **What the graph is** — 994 nodes / 2,357 edges / 51 communities; where the artifacts live; that `graph.json` is source of truth and `graph.html` is the visual.
2. **The query-first rule** (§4.1) with the four verified `graphify` commands.
3. **`eqr graph` command reference** (§2.2) with copy-paste examples.
4. **Community map** — the table in §1 (community → files) so a human can jump straight to a subsystem.
5. **Node-ID scheme** so agents can construct ids (`eqr/strategy/rank.py::rank_sleeve` → `eqr_strategy_rank_rank_sleeve`).
6. **Freshness & hooks** — how `built_at_commit` staleness works and that commits auto-rebuild (§6).
7. **`.graphifyignore` contract** — what is deliberately not graphed (data, secrets) and why.

---

## 5. File-by-File Code Implementation Roadmap

> **TDD is mandatory.** For each code item: write the failing test first (§6), watch it fail for the right reason, then write the minimal code. One logical commit per item; the post-commit hook rebuilds the graph automatically.

### `[NEW] eqr/spine/graph.py`
The `GraphifyReader` class and `rebuild()` helper from §3, verbatim. Placed in `spine/` because it is infrastructure with no strategy/research knowledge (siblings: `http.py`, `quality.py`). No new dependencies added to `pyproject`.

### `[MODIFY] eqr/cli.py` — register the `graph` group
Follows the file's existing Typer idiom exactly (sub-app + lazy imports inside commands). Insert near the other command definitions:

```python
graph_app = typer.Typer(help="Query the Graphify code graph (graphify-out/).", no_args_is_help=True)
app.add_typer(graph_app, name="graph")


@graph_app.command("status")
def graph_status():
    """Node/edge/community counts, build commit, and staleness vs HEAD."""
    from .spine.graph import GraphifyReader
    r = GraphifyReader()
    s = r.stats
    stale = r.is_stale()
    freshness = "UNKNOWN" if stale is None else ("STALE — run `eqr graph rebuild`" if stale else "FRESH")
    typer.echo(f"{s['nodes']} nodes · {s['edges']} edges · {s['communities']} communities")
    typer.echo(f"built_at_commit {str(s['built_at_commit'])[:8]}  →  {freshness}")


@graph_app.command("query")
def graph_query(target: str = typer.Argument(..., help="symbol, node id, or source file"),
                depth: int = typer.Option(1, "--depth"),
                as_json: bool = typer.Option(False, "--json")):
    """Neighbors + community hub for a symbol/file, grouped by relation."""
    from .spine.graph import GraphifyReader
    r = GraphifyReader()
    if as_json:
        ids = r.resolve(target)
        typer.echo(json.dumps({nid: [nb.__dict__ for nb in r.neighbors(nid)] for nid in ids}, indent=1))
    else:
        typer.echo(r.as_markdown(target, depth=depth))


@graph_app.command("hubs")
def graph_hubs(top: int = typer.Option(10, "--top")):
    """Community hubs (by node count) and the most-connected god nodes."""
    from .spine.graph import GraphifyReader
    r = GraphifyReader()
    typer.echo("Communities:")
    for name, n in list(r.communities().items())[:top]:
        typer.echo(f"  {n:>4}  {name}")
    typer.echo("God nodes:")
    for label, deg in r.god_nodes(top):
        typer.echo(f"  {deg:>4}  {label}")


@graph_app.command("explain")
def graph_explain(symbol: str = typer.Argument(...)):
    """Rich explanation — shells to `graphify explain`, falls back to `query`."""
    import shutil, subprocess
    if shutil.which("graphify"):
        raise typer.Exit(subprocess.run(["graphify", "explain", symbol]).returncode)
    from .spine.graph import GraphifyReader
    typer.echo(GraphifyReader().as_markdown(symbol))


@graph_app.command("rebuild")
def graph_rebuild(no_cluster: bool = typer.Option(False, "--no-cluster")):
    """Re-extract and re-cluster the graph (delegates to the graphify binary)."""
    from .spine.graph import rebuild
    try:
        raise typer.Exit(rebuild(no_cluster=no_cluster))
    except RuntimeError as e:
        raise typer.BadParameter(str(e))
```

### `[NEW] docs/GRAPHIFY_GUIDE.md`
Contents specified in §4.3. **Delegated to `documentation-engineer`** — not authored here.

### Optional, non-blocking
- `eqr/config.py`: add `graph_path` handling only if we prefer it centralized in `Settings`; otherwise `EQR_GRAPH_PATH` stays local to `spine/graph.py`. Not required.

---

## 6. Verification & Automated Testing Plan

### 6.1 Unit tests — `[NEW] tests/test_graph.py` (pytest, matching repo style)

Write these **before** `eqr/spine/graph.py` exists (they must fail on import first):

| Test | Asserts | Real anchor |
|---|---|---|
| `test_stats_match_artifacts` | `reader.stats["nodes"] == 994`, `edges == 2357`, `communities == 51` | live `graph.json` |
| `test_resolve_symbol_and_file` | `resolve("rank_sleeve")` → `["eqr_strategy_rank_rank_sleeve"]`; `resolve("eqr/strategy/rank.py")` non-empty | real node id |
| `test_neighbors_include_known_edges` | neighbors of `rank_sleeve` include an **in**-edge from `eqr/cli.py` and **out**-edges to `score`, `select`, `publish` | verified via `graphify explain` |
| `test_god_nodes_top_is_upsert` | `god_nodes(1)[0][0] == "upsert()"` (32 edges) | `graphify god-nodes` |
| `test_missing_graph_raises_actionable_error` | `FileNotFoundError` mentioning `eqr graph rebuild` when `EQR_GRAPH_PATH` points nowhere | — |
| `test_markdown_snippet_is_grouped_by_relation` | `as_markdown("rank_sleeve")` contains `→ calls` and `← imports` sections | — |

**Performance gate (<50 ms):** load once in a fixture, then assert repeated lookups are fast:
```python
def test_neighbor_lookup_under_50ms(graph_reader):
    graph_reader.stats                      # warm the cached_property (one-time JSON parse)
    import time
    t0 = time.perf_counter()
    for _ in range(100):
        graph_reader.neighbors("eqr_strategy_rank_rank_sleeve")
    assert (time.perf_counter() - t0) / 100 < 0.05
```
(The one-time parse of the 1.1 MB file is excluded from the per-lookup budget by warming the cache first — the honest thing to measure, since production callers reuse one reader.)

### 6.2 CLI smoke tests
- `test_graph_status_reports_fresh_when_head_matches` — monkeypatch `is_stale` → `False`, assert `"FRESH"` in output via Typer's `CliRunner`.
- `test_graph_query_cli_returns_zero_and_names_the_file` — `runner.invoke(app, ["graph", "query", "rank_sleeve"])`, exit 0, output contains `eqr/strategy/rank.py`.

### 6.3 Git-hook / freshness verification (mechanics already in place — verify, don't rebuild)

Confirmed from `.git/hooks/`:
- **`post-commit`**: runs `graphify update .` after a commit; **skips** during rebase/merge/cherry-pick, when only `graphify-out/` changed (no rebuild loop), and when `GRAPHIFY_SKIP_HOOK=1`. Resolves the Python interpreter via a pinned path → `graphify-out/.graphify_python` → `graphify` on PATH.
- **`post-checkout`**: runs **only on branch switches** (not file checkouts), and only if `graphify-out/` already exists. Same opt-out.

Validation steps (manual/CI, no numbers touched):
1. `eqr graph status` → confirm `built_at_commit` == `git rev-parse HEAD` after a commit that changes an `eqr/` file.
2. Touch a function in `eqr/strategy/rank.py`, commit, and confirm the hook re-ran (`graph.json` mtime advanced; `built_at_commit` updated).
3. `GRAPHIFY_SKIP_HOOK=1 git commit …` → confirm the graph is intentionally left stale and `eqr graph status` prints **STALE**.

### 6.4 Key-leakage / stale-graph guard (CI-lightweight, local)
- **Ignore-rules audit** (already correct — codify as a test): `.graphifyignore` excludes `data/` (the 879 MB `eqr.duckdb` and all `*.db`/`*.sqlite`/`*.csv`), `.env`/`.env.*`, and `**/*token*.json` / `**/*credential*.json` / `**/service-account*.json`. Add `test_no_data_or_secret_nodes_in_graph`: assert no node's `source_file` starts with `data/` or matches a secret glob — a regression tripwire if the ignore file is ever weakened.
- **Staleness gate for CI:** a `graph-freshness` check that fails if `built_at_commit != HEAD` on a code change (uses `GraphifyReader.is_stale()`), so a stale graph can't merge silently.

---

### Sequencing & guardrails
1. `tests/test_graph.py` (RED) → `eqr/spine/graph.py` (GREEN) → refactor. Commit.
2. CLI tests (RED) → `eqr/cli.py` `graph` group (GREEN). Commit.
3. Hand `docs/GRAPHIFY_GUIDE.md` (§4.3 spec) to **`documentation-engineer`**.
4. Any push of the above is delegated to **`production-engineer`** (no direct pushes). This plan changes **no research numbers, no DuckDB schema, no data** — it is pure read-only tooling over `graphify-out/`.
