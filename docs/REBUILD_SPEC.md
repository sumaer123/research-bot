# Rebuild Spec — Sumaer Research Bot (`eqr`)

The doc from which this project can be rebuilt from zero: this file plus the source repo stands
it back up on a machine that has neither. Patch incrementally on every infra/dependency/env/
schema change. Env-var VALUES never appear here — names only; real values live in the gitignored
`.env`, set by `production-engineer`.

## 1. Identity

Sumaer Research Bot (package `eqr`) — an independent, point-in-time Indian-equity research
engine: it ranks the NSE universe (two sleeves, validated before trusted) and writes Claude
research dossiers on request. It advises Project Upstox later through a read-only, fail-soft API
line; it never places an order. Personal project (`sumaer123@gmail.com`), no `fe-` tools. Owner:
Sumaer Bahl. Today it runs Mac-local only (model data-only phase); no production URL exists yet.
Planned host: a new non-OCI VM (Hetzner CX32 or GCP e2-standard-2 Mumbai) — the OCI box is
Upstox-only and this project is never deployed there.

## 2. Stack & runtime

- Python 3.13, venv at `.venv` managed by `uv`.
- CLI: console script `eqr` -> `eqr.cli:app` (Typer). Logging via stdlib `logging`, INFO level.
- Store: DuckDB, single file `data/eqr.duckdb`, no server process.
- Web: FastAPI + Jinja2, served by Uvicorn.
- Build backend: setuptools (`pyproject.toml`); package data ships `store/schema.sql`,
  `research/schema.json`, `surfaces/web/templates/*.html`, `surfaces/web/static/*`.
- Key runtime deps (`pyproject.toml`): duckdb, pandas, pyarrow, numpy, scipy, requests, fastapi,
  uvicorn[standard], jinja2, python-dotenv, typer, rich, jsonschema, pypdf, yfinance (declared in
  `pyproject.toml`; as of 2026-09-14 no module under `eqr/` actually imports it — verified by a
  full-package grep, zero matches. Treat it as reserved, not live).
- Dev/test deps: pytest, pytest-cov, httpx. Test command: `.venv/bin/python -m pytest -q`
  (39 tests, all passing as of 2026-09-14).

## 3. Repo layout

- `eqr/store/` — `db.py` (connect/init), `pit.py` (`as_of_view` and PIT helpers), `schema.sql`
  (every table, see §7).
- `eqr/spine/` — `http.py` (rate-limited session, NSE cookie warm-up, proxy fallback),
  `nse_archives.py` (bhavcopy 3 formats, MTO, index closes, EQUITY_L, F&O ban, deals),
  `nse_api.py` (corporate actions, filing dates, ASM/GSM, shareholding, announcements),
  `screener.py` (screener.in parser + PIT statements loader), `adjust.py` (split/bonus factor
  detection + tape confirmation), `universe.py` (PIT liquidity universe), `quality.py`
  (post-refresh quality harness), `refresh.py` (`daily_refresh` / `backfill` orchestration).
- `eqr/features/` — `price.py`, `fundamental.py`, `panel.py` (loads the rolling window),
  `xsection.py` (winsorise/z-score/bucket), `build.py` (`build_features`).
- `eqr/strategy/` — `regime.py`, `sleeves.py` (`SleeveConfig.L` / `.S`), `sizing.py`, `rank.py`
  (`rank_sleeve`, `validated_config` — reads the latest walk-forward verdict to pick N/variant).
- `eqr/validate/` — `costs.py`, `backtest.py`, `walkforward.py`, `metrics.py`, `acceptance.py`,
  `report.py` (writes `data/reports/<kind>-<timestamp>-<hash>/report.md` + supporting CSV/JSON).
- `eqr/research/` — `docstore.py` (filing/document sync), `pack.py` (`build_pack`), `dossier.py`
  (`run_dossier`), `schema.py` / `schema.json` (dossier JSON schema).
- `eqr/surfaces/` — `web/app.py` (FastAPI app) + `web/templates/*.html` + `web/static/`,
  `queries.py`, `md.py`, `digest.py`, `telegram.py` (send-only), `advisor_client.py` (reference
  client for Upstox's future R6 integration — fail-soft by construction).
- `eqr/cli.py` — every command (§8). `eqr/config.py` — env/settings loading.
- `deploy/` — `install.sh` (idempotent VM setup), `backup.sh` (restic), `Caddyfile` (TLS
  reverse-proxy, `__DOMAIN__` placeholder), `systemd/*.service` + `*.timer` (§9).
- `tests/` — 39 tests + `fixtures/` (3 bhavcopy formats, MTO, index CSV, a screener HTML
  snippet, etc.).
- `data/` — gitignored. `eqr.duckdb`, `raw/` (immutable fetch cache), `reports/`, `docs/`
  (filing PDFs + text sidecars), `packs/`.
- `.env.example` — env-var names only (§5). `.gitignore` — excludes `data/`, `.env`, caches.

## 4. Infrastructure

- **Hosting today:** none — Mac-local only, run by hand (`eqr web`, `eqr refresh`, …), no
  launchd job installed yet.
- **Hosting planned:** Hetzner CX32 (4 vCPU / 8 GB / 80 GB, ~EUR 7/mo) or GCP e2-standard-2
  Mumbai (if an Indian egress IP matters more than cost); Ubuntu 24.04; `uv`-managed Python;
  systemd timers; Caddy for TLS. Provisioning (account + payment) is Sumaer's; `deploy/` is
  written so `install.sh` can stand the box up unattended once it exists.
- **Database:** DuckDB, single file, no separate DB host, no managed service.
- **Object storage:** none for primary data. Backup target is Backblaze B2 via restic
  (`RESTIC_REPOSITORY`, e.g. `b2:bucket-name:eqr`). `deploy/backup.sh` excludes
  `data/raw/nse/bhav`, `data/raw/nse/mto` and `data/packs` from the snapshot (large and
  re-fetchable), and keeps 14 daily / 8 weekly / 12 monthly snapshots via `restic forget
  --prune`. It exits 0 and skips silently if `RESTIC_REPOSITORY` is unset — a quiet no-op, not a
  failure, so a real restore test is the only way to know backups are actually happening.
- **Domains/DNS:** none registered. `Caddyfile` takes a `__DOMAIN__` placeholder that
  `install.sh` fills from `EQR_DOMAIN` only if that variable is set.
- **MCP servers:** none.
- **launchd/cron (Mac):** none installed. **systemd (VM, once provisioned):** see §9.

## 5. Environment variables

Names and purpose only — values live in the gitignored `.env` (copied from `.env.example` by
`deploy/install.sh` on first run), set for real by `production-engineer`.

| Name | Purpose | Where set | Required? |
|---|---|---|---|
| `EQR_DATA_DIR` | Override the data directory (default: `<project>/data`) | `.env` | optional |
| `EQR_RATE_LIMIT_S` | Minimum seconds between requests to the same host | `.env` | optional |
| `EQR_PROXY` | SOCKS5h WARP proxy URL (e.g. `socks5h://127.0.0.1:40000`) for NSE API calls from a datacenter IP, which 403s | `.env` | required only when the box's egress IP is not residential/Indian |
| `EQR_ADVISOR_TOKEN` | Bearer token guarding `GET /advisor/v1/*` | `.env` | required before the advisor API is reachable off `127.0.0.1` |
| `EQR_WEB_HOST` | Bind host for `eqr web` | `.env` | optional |
| `EQR_WEB_PORT` | Bind port for `eqr web` | `.env` | optional |
| `TELEGRAM_BOT_TOKEN` | Send-only bot token for the daily digest | `.env` | required for `eqr digest --send` |
| `TELEGRAM_CHAT_ID` | Destination chat for the digest | `.env` | required for `eqr digest --send` |
| `ANTHROPIC_API_KEY` | Optional API path for dossiers | `.env` | optional — unset uses the `claude` CLI on the Mac instead |
| `EQR_CLAUDE_MODEL` | Model name for dossier runs | `.env` | optional |
| `EQR_RISK_FREE_PCT` | Risk-free rate used to price the regime's cash sleeve | `.env` | optional |
| `RESTIC_REPOSITORY` | Restic backup repository target | `.env` on the VM | required for `deploy/backup.sh` to do anything |
| `RESTIC_PASSWORD` | Restic repository password | `.env` on the VM | required with `RESTIC_REPOSITORY` |
| `B2_ACCOUNT_ID` | Backblaze B2 account id (restic backend) | `.env` on the VM | required with `RESTIC_REPOSITORY` |
| `B2_ACCOUNT_KEY` | Backblaze B2 account key (restic backend) | `.env` on the VM | required with `RESTIC_REPOSITORY` |

## 6. External integrations & data sources

Full detail (URL pattern, cadence, verified depth, PIT rule, failure mode) lives in one place:
`docs/DATA_SOURCES.md` — this section only names them and the auth/RW shape.

| Integration | Auth | RO/RW |
|---|---|---|
| NSE archives (`nsearchives.nseindia.com`) | none (public CSV/zip) | read-only |
| NSE API (`www.nseindia.com/api/*`) | cookie warm-up (no login); `EQR_PROXY` fallback on 403 | read-only |
| screener.in company pages | none (public HTML) | read-only |
| Telegram Bot API | `TELEGRAM_BOT_TOKEN` | write-only (send the digest) |
| Anthropic (Claude Code CLI on the Mac, or API with `ANTHROPIC_API_KEY`) | CLI session or API key | reads the pack, writes the dossier back into DuckDB — never touches an order path |
| Backblaze B2 (via restic) | `B2_ACCOUNT_ID` / `B2_ACCOUNT_KEY` | write-only backup target |
| Project Upstox (`eqr/surfaces/advisor_client.py`) | `EQR_ADVISOR_TOKEN` bearer | read-only, one direction (Upstox reads this project); not wired up yet — R6, after a sleeve is validated in production |

## 7. Data model & migrations

Single schema file, no migration framework: `eqr/store/schema.sql`, applied idempotently
(`CREATE TABLE IF NOT EXISTS …`) by `eqr init` / `connect()`. Schema changes are edits to that
file plus a re-run of `eqr init` — additive changes are safe; anything destructive needs
`production-engineer`'s explicit review per the global doctrine. Tables (grouped by layer):

- **Store/spine:** `instruments`, `prices_daily`, `trading_days`, `adj_factors`, `index_daily`,
  `corporate_actions`, `statements`, `statement_revisions`, `shareholding`, `results_calendar`,
  `surveillance`, `fo_ban`, `deals`, `announcements`, `documents`, `screener_meta`, `fetch_log`,
  `quality_checks`, `runs`, `holidays`, `factor_anomalies`, `etf_list`.
- **Features/strategy:** `universe_monthly`, `features`, `ranks`, `regime_daily`.
- **Validate/research:** `backtests`, `dossiers`.

No seeds — every table is populated by a spine fetch or a derived computation, never hand-typed
data.

## 8. Build · run · deploy

Install (fresh machine): see §10. Local run (Mac, already installed) — every CLI command:

```
.venv/bin/eqr init
.venv/bin/eqr refresh [--date YYYY-MM-DD | --backfill-from YYYY-MM-DD [--backfill-to YYYY-MM-DD]] [--no-snapshots] [--no-universe]
.venv/bin/eqr reference [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--no-surveillance]
.venv/bin/eqr fundamentals [--symbols A,B] [--fetch-only | --load-raw] [--rate SECONDS] [--limit N]
.venv/bin/eqr factors [--from YYYY-MM-DD]
.venv/bin/eqr universe [--as-of YYYY-MM-DD] [--monthly-from YYYY-MM-DD]
.venv/bin/eqr features [--as-of YYYY-MM-DD] [--monthly-from YYYY-MM-DD] [--regime/--no-regime]
.venv/bin/eqr rank [--sleeve L|S] [--as-of YYYY-MM-DD] [--top N] [--variant NAME]
.venv/bin/eqr backtest [--sleeve L|S] [--start DATE] [--end DATE] [--capital N] [--top N] [--variant NAME] [--zero-brokerage]
.venv/bin/eqr validate [--sleeve L|S] [--start DATE] [--end DATE] [--holdout-start DATE] [--capital N] [--first-fold-year YYYY]
.venv/bin/eqr filings SYMBOL[,SYMBOL...] [--docs/--no-docs]
.venv/bin/eqr pack SYMBOL [--as-of YYYY-MM-DD]
.venv/bin/eqr dossier SYMBOL [--as-of YYYY-MM-DD] [--model NAME] [--dry-run]
.venv/bin/eqr web [--host HOST] [--port PORT]
.venv/bin/eqr digest [--send]
.venv/bin/eqr doctor
```

Test: `.venv/bin/python -m pytest -q`. Deploy (once the VM exists): via `production-engineer`
only — `deploy/install.sh` (idempotent; re-run after every `git pull` on the box). Env/secrets:
via `production-engineer` only. Gotcha: `eqr fundamentals --fetch-only` is deliberately DB-free
(archives HTML to disk) so it is safe to run while another process holds the DuckDB file; run
`--load-raw` afterwards to parse the archive into the store.

## 9. Scheduled jobs / daemons

None on the Mac today (everything above is run by hand). On the VM, once provisioned, five
systemd units (`deploy/systemd/`):

| Unit | Trigger | What it does |
|---|---|---|
| `eqr-web.service` | `multi-user.target`, `Restart=always` | Long-running: dashboard + advisor API on `127.0.0.1:8801` |
| `eqr-refresh.timer` -> `.service` | daily 14:15 UTC (19:45 IST) | `eqr refresh`, then `eqr reference --from <today-45d>` |
| `eqr-fundamentals.timer` -> `.service` | weekly, Friday 20:30 UTC (Saturday 02:00 IST) | `eqr fundamentals --rate 1.5`, then `eqr features`, then `eqr rank --sleeve L` and `--sleeve S` |
| `eqr-digest.timer` -> `.service` | daily 02:00 UTC (07:30 IST) | `eqr digest --send` |
| `eqr-backup.timer` -> `.service` | daily 16:00 UTC (21:30 IST) | `deploy/backup.sh` — restic backup of `data/` to Backblaze B2 |

All timers set `Persistent=true` (a missed run fires on next boot); the refresh timer also sets
`RandomizedDelaySec=300`.

## 10. Recreate-from-scratch checklist

1. Provision the VM (Hetzner CX32 or GCP e2-standard-2 Mumbai), Ubuntu 24.04, root SSH —
   Sumaer's step (account + payment).
2. Get this repo onto the box (or let `install.sh` do it — it clones `EQR_REPO_URL`, default
   `https://github.com/sumaer123/research-bot.git`, once that remote exists; production-engineer
   creates it).
3. Run `deploy/install.sh` as root: creates the `eqr` system user, installs `git`/`curl`/`unzip`/
   `restic`/`uv`, builds `.venv` with `uv venv --python 3.13` + `uv pip install -e '.[dev]'`,
   copies `.env.example` -> `.env` (values must then be filled in by `production-engineer`), runs
   `eqr init`, installs the systemd units, enables `eqr-web.service` plus the four timers,
   installs Caddy and reloads it only if `EQR_DOMAIN` is set, and runs the test suite as a
   sanity gate.
4. Fill in `.env` real values (§5) — `production-engineer` only, never in a doc.
5. Backfill history: `eqr refresh --backfill-from 2016-01-01`, `eqr reference --from
   2016-01-01`, `eqr fundamentals --fetch-only` then `--load-raw` (the screener.in sweep takes
   hours at <=1 req/s for ~2,000 symbols — expect it to run over more than one day), `eqr
   factors`, `eqr features --monthly-from 2017-01-01`.
6. Rank and validate both sleeves: `eqr rank --sleeve L`, `eqr rank --sleeve S`, `eqr validate
   --sleeve L`, `eqr validate --sleeve S` — compare the new `data/reports/validate-*/report.md`
   verdicts against `docs/VALIDATION.md`'s recorded 2026-09-14 outcome before trusting a rank.
7. Point Caddy/DNS at the box if a public hostname is wanted (`EQR_DOMAIN` + re-run
   `install.sh`); otherwise the dashboard stays reachable only via `127.0.0.1:8801` (SSH tunnel
   from the Mac).
8. Verify: `eqr doctor` (live smoke, one fetch per source) and `systemctl list-timers 'eqr-*'`
   (all five units enabled and scheduled).
