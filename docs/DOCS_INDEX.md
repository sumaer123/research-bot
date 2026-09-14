# Docs Index — Sumaer Research Bot (`eqr`)

Map of every doc in this project, plus an append-only log of what changed. Maintained by the
`documentation-engineer` agent — never hand-edit. Master index row: `Sumaer's Claude Data/
DOCUMENTATION_INDEX.md`. Registry key `research-bot`.

## Part A — Map

| Doc | What it is | Status |
|---|---|---|
| `README.md` | Entry point: what it is, architecture, quick start, the two sleeves, validation verdicts + caveats, advisor contract, guardrails | CURRENT |
| `docs/DOCS_INDEX.md` | This file | CURRENT |
| `docs/REBUILD_SPEC.md` | Rebuild-from-zero spec: stack, repo layout, infra, env-var names, data model, build/run/deploy, systemd jobs, recreate checklist | CURRENT |
| `docs/DATA_SOURCES.md` | Every data source: URL pattern, cadence, verified history depth, PIT rule, failure mode | CURRENT |
| `docs/OPERATIONS.md` | Daily/weekly runbook, quality checks and what a FAIL means, running a dossier, the Upstox R6 plan, known open items | CURRENT |
| `docs/VALIDATION.md` | Pre-registered validation protocol, acceptance bar, both sleeves' 2026-09-14 outcome with fold tables | CURRENT |
| `docs/superpowers/specs/2026-09-14-research-bot-design.md` | Approved design spec (source of truth for architecture, PIT rules, spine facts §4.2, validation outcome §12a) — skill artefact | REFERENCE (do not edit) |
| `docs/superpowers/plans/2026-09-14-research-bot-plan.md` | Build plan, 15 tasks, each with a done-when test | REFERENCE (do not edit) |
| `.env.example` | Env-var NAMES only (never values) | CURRENT |
| `pyproject.toml` | Package metadata, dependencies, `eqr` console entry point | CURRENT |
| `eqr/store/schema.sql` | All DuckDB tables (store of record for the schema) | CURRENT |
| `deploy/install.sh`, `deploy/backup.sh`, `deploy/Caddyfile`, `deploy/systemd/*` | Rebuild/ops artefacts — indexed here, owned by production-engineer for anything beyond reading | CURRENT |

No `_archive/` yet — nothing superseded since this is the initial onboarding.

## Part B — Log (append-only)

| Date | Change | Files | By |
|---|---|---|---|
| 2026-09-14 | Initial docs onboarding. Read the approved design spec + build plan + live code (`eqr/cli.py`, `eqr/surfaces/advisor_client.py`, `eqr/store/schema.sql`, `eqr/spine/nse_archives.py`, `eqr/spine/refresh.py`, `deploy/`, `.env.example`) and the validation reports, identified by their own first line (`data/reports/validate-20260914-063318-1219c7/report.md` = Sleeve L, VALIDATED; `data/reports/validate-20260914-064307-495ffd/report.md` = Sleeve S, NOT VALIDATED — the second of two S runs made today, superseding `...-bce33a`'s duplicate-row robustness-table artifact, verdict unchanged), to write 6 new docs from scratch. Added `research-bot` to `.docs-toolkit/docs-registry.json` and a row to the master index. Repo was already 2 commits deep on `main` with no remote; this pass adds a 3rd commit, doc paths only, no push (production-engineer creates the remote). | `README.md`, `docs/DOCS_INDEX.md`, `docs/REBUILD_SPEC.md`, `docs/DATA_SOURCES.md`, `docs/OPERATIONS.md`, `docs/VALIDATION.md` (all created) · `.docs-toolkit/docs-registry.json` (entry added) · `DOCUMENTATION_INDEX.md` (row + log line added) | documentation-engineer (initial onboarding) |
| 2026-09-14 | **Registered and pushed to GitHub** (production-engineer, DOC-PAYLOAD finalize). Added `research-bot` to `.deploy-toolkit/registry.json` (model `data-only`, root `Project Research Bot`, branch `main`, guards/pushAutoDeploys/sqlMigrations/envChangesByAgent all `false`; note: OCI is Upstox-only, never deploy there — `deploy/` artefacts wait for the future non-OCI VM). Created private remote `https://github.com/sumaer123/research-bot` and pushed `main` — pushed HEAD `648bdfc` (8 commits: `1dd177c`→`118ec43`→`f261942`→`5a300b4`→`f44a7ab`→`a64304f`→`0ea8b98`→`648bdfc`), 106 tracked files, verified no `data/` and no `.env` in the pushed tree. Ledger: `.deploy/DEPLOY_HISTORY.md`. This pass (documentation-engineer): added the repo URL/registry facts to `README.md` and `docs/REBUILD_SPEC.md` §1, this log line, and the master-index row. | `README.md`, `docs/REBUILD_SPEC.md`, `docs/DOCS_INDEX.md` (this line) · Master: `DOCUMENTATION_INDEX.md` (row) · `.deploy-toolkit/registry.json` + `.deploy/DEPLOY_HISTORY.md` (production-engineer) | documentation-engineer (finalize) |
