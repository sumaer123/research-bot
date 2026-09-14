# Graphify Guide — Sumaer Research Bot (`eqr`)

Developer and agent reference for the code graph integration. The graph maps every symbol,
function, and file in `eqr/` into a queryable network so you can locate code, measure blast
radius, and orient subagents without reading whole directories.

---

## 1. What the graph is

The graph lives in `graphify-out/`:

| Artifact | Purpose |
|---|---|
| `graphify-out/graph.json` | Source of truth — all nodes, edges, metadata |
| `graphify-out/graph.html` | Interactive visual (open in any browser) |
| `graphify-out/GRAPH_REPORT.md` | Human-readable summary of topology and communities |
| `graphify-out/.graphify_labels.json` | Community-id → name mapping |

**Verified topology (built at commit `fdca0ebe`):** 994 nodes · 2,357 edges · 51 communities.
99% of edges are EXTRACTED (AST-derived); 26 are INFERRED. The graph is undirected, no multigraph,
no hyperedges.

**Relation types** (by frequency): `calls` 777 · `contains` 608 · `references` 333 · `imports`
253 · `rationale_for` 160 · `imports_from` 134 · `extends` 35 · `method` 27 · `indirect_call`
14 · `uses` 9.

---

## 2. Query-first rule

> Before any Grep or directory Read to locate code, run one graph query. Then read only the
> `source_file:source_location` values the query returns. Never sweep whole directories.

A `UserPromptSubmit` hook (`graphify-first`) already nudges this for agents; the rule applies
to humans too. One query replaces ten file reads.

### The four `graphify` binary commands

```bash
# Find a symbol — returns files, line numbers, and direct neighbors
graphify query "rank_sleeve"

# What breaks if I change this file?
graphify affected "eqr/research/schema.py"

# Prose explanation of a single node and its neighborhood
graphify explain "rank_sleeve"

# How do two symbols connect through the graph?
graphify path "dossier()" "upsert()"
```

All four commands read `graphify-out/graph.json` — they work offline without network access.
The binary is installed at `~/.local/bin/graphify`.

### Worked example — adding a fundamental factor

1. `graphify query "fundamental features"` → lands on `eqr/features/fundamental.py`
   (community 11: `_piotroski`, `_altman`, `fundamental_features`).
2. `graphify affected "eqr/features/fundamental.py"` → `build_features()` (community 9) and
   `rank_sleeve()` consume it; blast radius reaches Sleeve Ranking.
3. Read only those two files. Make the change. The `post-commit` hook rebuilds the graph.

---

## 3. `eqr graph` command reference

The `graph` sub-app is registered in `eqr/cli.py` (`app.add_typer(graph_app, name="graph")`).
Commands `status`, `query`, and `hubs` read `graph.json` in-process via `GraphifyReader` — no
subprocess, no `graphify` package required, works in CI. `explain` and `rebuild` shell out to
the `graphify` binary when present.

### `eqr graph status`

Node/edge/community counts, `built_at_commit`, and FRESH/STALE verdict vs `git rev-parse HEAD`.

```
$ eqr graph status
994 nodes · 2357 edges · 51 communities
built_at_commit fdca0ebe  →  FRESH
```

### `eqr graph query <target>`

Resolves a symbol, node id, or source file to its node; prints direct neighbors grouped by
relation and the community it belongs to. `--depth N` (default 1) expands further;
`--json` for machine-readable output.

```
$ eqr graph query rank_sleeve

### `rank_sleeve()` — eqr/strategy/rank.py:L16 · community _Sleeve Ranking & Regime_
- **← calls**: `rank()` (eqr/cli.py:L246), `_prep()` (tests/test_surfaces.py:L23)
- **← imports**: ...
- **→ calls**: `upsert()` (eqr/store/db.py:…), `score()` (eqr/strategy/…),
               `select()`, `publish()`, `regime_at()`, `inverse_vol_weights()`, `rank_table()`
- **→ references**: `SleeveConfig`, `DuckDBPyConnection`
```

### `eqr graph hubs [--top N]`

Community hubs by node count and the most-connected god nodes.

```
$ eqr graph hubs --top 4
Communities:
    81  CLI & Command Layer
    68  NSE Document Ingestion
    62  Digest & Markdown Rendering
    54  Claude Dossier Runner
God nodes:
    32  upsert()
    31  load_parsed_xbrl()
    29  refresh_factors()
    28  connect()
```

### `eqr graph explain <symbol>`

Rich plain-language explanation. Shells to `graphify explain` when the binary is on PATH; falls
back to `query`-style output otherwise.

```bash
eqr graph explain build_features
```

### `eqr graph rebuild [--no-cluster]`

Forces a full re-extraction (`graphify update .`). Refuses with an install hint if the binary
is not on PATH. Normally you do not need this — the `post-commit` hook handles it automatically.

```bash
eqr graph rebuild            # re-extract + re-cluster
eqr graph rebuild --no-cluster   # re-extract only, skip community detection
```

---

## 4. Community map — jump straight to a subsystem

| ID | Community | Primary files |
|---|---|---|
| 8 | Sleeve Ranking & Regime | `eqr/strategy/rank.py`, `sleeves.py`, `regime.py` |
| 9 | Feature Building Pipeline | `eqr/features/build.py`, `panel.py` |
| 11 | Fundamental Features | `eqr/features/fundamental.py` |
| 39 | Price Features | `eqr/features/price.py` |
| 3 | Claude Dossier Runner | `eqr/research/dossier.py` |
| 1 | NSE Document Ingestion | `eqr/research/docstore.py` |
| 10 | DuckDB Store Layer | `eqr/store/db.py` |
| 16 | Quality Gate & Checks | `eqr/store/quality_gate.py`, `eqr/spine/quality.py` |
| 13 | Trial Ledger | `eqr/validate/trials.py` |
| 14 | Prospective Forward Ledger | `eqr/validate/prospective.py` |
| 20 | Backtest Engine | `eqr/validate/backtest.py` |
| 23 | Acceptance & Walk-Forward | `eqr/validate/walkforward.py` |
| 17 | Performance Metrics | `eqr/validate/costs.py` |

For the dossier/claim schema communities (ids 19/21/24/26–29/33–36), query
`graphify query "schema"` — they share `eqr/research/schema.py` and `eqr/research/schema.json`.

---

## 5. God nodes — high blast radius; edit with care

These are the most-connected symbols (full-degree count, container/file nodes excluded). A
change to any of them propagates across multiple communities.

| Symbol | Degree | File |
|---|---|---|
| `upsert()` | 32 | `eqr/store/db.py` |
| `load_parsed_xbrl()` | 31 | `eqr/spine/xbrl.py` |
| `refresh_factors()` | 29 | `eqr/spine/refresh.py` |
| `connect()` | 28 | `eqr/store/db.py` |
| `run_backtest()` | 28 | `eqr/validate/backtest.py` |
| `build_features()` | 27 | `eqr/features/build.py` |
| `make_synthetic_market()` | 25 | `eqr/validate/backtest.py` |
| `Http` | 23 | `eqr/spine/http.py` |
| `NseApi` | 23 | `eqr/spine/nse_archives.py` |
| `parse_xbrl()` | 23 | `eqr/spine/xbrl.py` |

Before editing any of these, run `graphify affected <file>` to see the full set of callers.
`connect()` and `upsert()` are cross-community bridges (high betweenness) — changes to them
have the widest spread.

---

## 6. Node-ID scheme

The graph assigns each node a stable, deterministic id from its dotted module path + symbol:

```
eqr/strategy/rank.py :: rank_sleeve   →   eqr_strategy_rank_rank_sleeve
eqr/store/db.py      :: upsert        →   eqr_store_db_upsert
eqr/cli.py           (file node)      →   eqr_cli
deploy/backup.sh     (file node)      →   deploy_backup
```

Rule: slashes and dots in the path become `_`; the symbol name is appended after the last `_`.
Use this scheme to build ids for `GraphifyReader.neighbors(node_id)` calls, or to bookmark a
node for a subagent brief.

---

## 7. Freshness and git hooks

`graph.json` stores a `built_at_commit` field. `eqr graph status` compares it to
`git rev-parse HEAD` and prints FRESH or STALE.

**Automatic rebuild via git hooks** (both installed and executable in `.git/hooks/`):

- **`post-commit`** — runs `graphify update .` after every commit that changes non-`graphify-out/`
  files. Skips automatically during rebase, merge, and cherry-pick (to avoid loops).
  To skip on purpose: `GRAPHIFY_SKIP_HOOK=1 git commit …`
- **`post-checkout`** — rebuilds on branch switches (not file checkouts); only fires if
  `graphify-out/` already exists.

When the graph is stale (e.g. after a `GRAPHIFY_SKIP_HOOK` commit or a rebase):

```bash
eqr graph rebuild      # forces graphify update .
eqr graph status       # confirm FRESH
```

A CI `graph-freshness` check (`GraphifyReader.is_stale()`) fails if `built_at_commit != HEAD`
on a code change — a stale graph cannot merge silently.

---

## 8. `.graphifyignore` contract — what is NOT graphed

The following are deliberately excluded from the graph:

| Pattern | Why excluded |
|---|---|
| `data/` (includes `eqr.duckdb`, `*.db`, `*.sqlite`, `*.csv`) | The ~879 MB DuckDB store; graphing it adds no code topology and bloats the artifact |
| `.env`, `.env.*` | Secrets — must never appear as graph nodes |
| `**/*token*.json`, `**/*credential*.json`, `**/service-account*.json` | Credentials |

A regression test (`tests/test_graph.py::test_no_data_or_secret_nodes_in_graph`) asserts that
no node's `source_file` starts with `data/` or matches any secret glob. If the ignore file is
weakened, this test fails before any commit merges.

---

## 9. Python API (`eqr.spine.graph`)

Use `GraphifyReader` directly when you need graph data inside the app — the CLI commands use
it under the hood.

```python
from eqr.spine.graph import GraphifyReader

r = GraphifyReader()            # loads graph.json once; cached_property caches the parse
r.stats                         # {"nodes": 994, "edges": 2357, "communities": 51, ...}
r.is_stale()                    # True/False/None (None = no git HEAD available)
r.resolve("rank_sleeve")        # ["eqr_strategy_rank_rank_sleeve"]
r.neighbors("eqr_strategy_rank_rank_sleeve")  # list[Neighbor] with relation + direction
r.god_nodes(top=5)              # [("upsert()", 32), ("load_parsed_xbrl()", 31), ...]
r.communities()                 # {"CLI & Command Layer": 81, ...} sorted by size
r.as_markdown("rank_sleeve")    # Markdown snippet ready to paste into an LLM context
```

`EQR_GRAPH_PATH` overrides the default `<PROJECT_ROOT>/graphify-out/graph.json` location —
useful in tests (`monkeypatch.setenv("EQR_GRAPH_PATH", str(tmp_path / "graph.json"))`).

`rebuild(no_cluster=False)` shells to the `graphify` binary; raises `RuntimeError` if the
binary is not on PATH (with the install hint).

---

## 10. Subagent prompt template

When dispatching a subagent to work on a specific subsystem, prepend this block instead of
dumping raw file contents:

```
You are editing the {COMMUNITY_NAME} subsystem (community {ID}) of the eqr research engine.
Graph context from graphify-out/graph.json @ {BUILT_AT_COMMIT}:

Files in this community:
{source_file values for nodes where community_name == COMMUNITY_NAME}

Cross-community bridges with wide blast radius — do NOT change their signatures:
{god_nodes touching this community from eqr graph hubs}

Direct dependents of the symbol you will change:
{output of: eqr graph query <TARGET>}

Rule: read only the files/lines cited above. If you need more context, run
`graphify query "<narrower question>"` — do not read whole directories.
```
