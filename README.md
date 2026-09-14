# Sumaer Research Bot (`eqr`)

Personal, independent Indian-equity research engine. It ranks the full NSE universe with a
point-in-time (PIT) quantitative engine — an edge that is measured before it is trusted — and
writes Claude-authored research dossiers on request, grounded in stored filings. It advises
Project Upstox later through a read-only API as one fail-soft evidence line; it never places an
order and never bypasses an Upstox gate.

Non-goals: order execution, intraday data, options, paid data feeds, any change to the Upstox
repo or its OCI box.

Personal project (`sumaer123@gmail.com`) — no `fe-` tools. Package `eqr`, root: this folder.
Repo: private GitHub [`sumaer123/research-bot`](https://github.com/sumaer123/research-bot)
(`origin`, branch `main`). Deploy-toolkit registry key `research-bot`, model **data-only** —
runs on the Mac today; the non-OCI VM in `docs/REBUILD_SPEC.md` does not exist yet.

## Architecture

One repo, strict layers. The contract between layers is DuckDB tables with documented schemas —
a layer never calls another layer's fetchers.

```
NSE archives/API, screener.in
        |  fetch -> data/raw/ (immutable)
        v
   eqr/store        data/eqr.duckdb -- schema.sql, connect/init, upsert, as_of_view (PIT reads)
        ^
        |  curated rows (as_of + visible_from)
   eqr/spine        archives . nse_api . screener . adjust (split/bonus factors) . universe . quality
        |
        v
   eqr/features      price / fundamental / valuation factors -> cross-section z-scores (build.py)
        |
        v
   eqr/strategy      regime . Sleeve L (monthly) . Sleeve S (weekly) . sizing . rank
        |
        v
   eqr/validate      costs . backtest . walk-forward . deflated Sharpe . acceptance bar . reports
        |
        v
   eqr/research      docstore (filings) . pack (JSON evidence pack) . dossier (Claude, cited, validated)
        |
        v
   eqr/surfaces      web (FastAPI dashboard) . advisor API (/advisor/v1/evidence) . Telegram digest
```

Code copied from Project Upstox (copies, never a shared tree, never edited back): fundamentals
models, OHLCV helpers, NSE session warm-up, screener parser skeleton, Telegram sender.

## Quick start (Mac, local dev)

The venv already exists at `.venv` (managed with `uv`, Python 3.13). To rebuild it from zero:

```
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

Then, in order:

```
.venv/bin/eqr init                                      # create data/ + DuckDB schema
.venv/bin/eqr refresh --backfill-from 2016-01-01         # EOD prices, index closes, snapshots
.venv/bin/eqr reference                                  # NSE cookie API: corp actions, filing dates, surveillance
.venv/bin/eqr fundamentals --fetch-only                   # screener.in sweep: archive HTML only
.venv/bin/eqr fundamentals --load-raw                     # parse the archived HTML into statements
.venv/bin/eqr factors                                     # detect split/bonus adjustment factors
.venv/bin/eqr features --monthly-from 2017-01-01          # cross-sectional factors, every month-end
.venv/bin/eqr rank --sleeve L                              # (and --sleeve S)
.venv/bin/eqr validate --sleeve L                          # (and --sleeve S) -- pre-registered walk-forward
.venv/bin/eqr web                                          # dashboard + advisor API on 127.0.0.1:8801
```

`eqr universe --monthly-from <date>` persists the monthly point-in-time liquidity universe for
reporting and the quality harness (feature and rank eligibility is filtered independently, so
this step is informational, not a hard prerequisite). `eqr doctor` runs one live fetch per source
plus row counts for the core tables — the fastest way to tell whether the Mac's network path to
NSE is healthy today.

Full command reference: `docs/REBUILD_SPEC.md` §8. Every command above except `web`/`doctor`
writes to `data/eqr.duckdb` or `data/raw/`.

## Running on macOS (production)

To run the dashboard, refresh, fundamentals, and digest tasks unattended via launchd:

```
bash deploy/mac/install-mac.sh
```

This installs four agents that run on a fixed schedule (IST): web always, refresh at 19:45 daily,
fundamentals at 02:00 Saturday, digest at 07:30 daily. Logs go to `~/Library/Logs/eqr/`. For
details (schedules, logs, TCC gotchas, removal), see `docs/OPERATIONS.md` "Running on the Mac (launchd)".

## The two sleeves

- **Sleeve L — Compounders** (monthly rebalance). Score = 0.30 quality + 0.25 value +
  0.30 momentum + 0.15 low-risk (industry-relative z-scores). Universe: >=250 sessions history,
  close >= Rs 20, median 120-day traded value >= Rs 1 cr, not ASM stage >=2 / F&O-banned,
  `pat_ttm > 0`. Top 30, holds while inside the top 45 (rank hysteresis).
- **Sleeve S — Tactical** (weekly rebalance). Score = 0.40 1-day momentum + 0.30 breakout
  (near 52-week high plus a volume surge) + 0.30 delivery surge. Rs 3 cr liquidity floor. Top 20,
  holds while inside the top 30, hard stop -8% from entry. No new entries in RISK_OFF.

Both emit target weights only (inverse 60-day volatility, capped 5%/name and 25%/industry, scaled
by the regime's exposure); execution is out of scope for this project.

## Validation verdicts (2026-09-14, first run of the pre-registered protocol)

**Sleeve L: PROVISIONAL** (claim-state ladder step 2 of 4). Out-of-sample time-weighted CAGR
28.7% vs 17.1% for the NIFTY 500 TR proxy, Sharpe 1.28 vs 0.73, max drawdown -22.2% vs -37.8%,
information ratio 0.72, deflated-Sharpe p = 0.005 (6 trials), 4 of 4 recent folds beat the index,
robust across N in {20,30} and the Rs 1cr/Rs 3cr liquidity floors, median order 0.03% of ADV20 at
Rs 10 lakh capital. Holdout (Sep-2025 -> Sep-2026, evaluated once): 21.9% vs 1.9%, Sharpe 0.98.
Cost model: 50 bps impact coefficient; risk-free rate from `EQR_RISK_FREE_PCT` (default 6.0%).

Six verified integrity items hold this rating at PROVISIONAL, not BACKTEST_PASS, until resolved:
AS_RESTATED_FUNDAMENTALS, MCAP_NOT_SPLIT_INVARIANT, HOLDOUT_INSPECTED, TRIALS_UNDERCOUNTED,
CONTROLS_NO_HISTORY, BENCH_PROXY. The holdout was burned (inspected during tuning), which is
correct but requires explicit recording. Read the design spec (§12a) and `docs/VALIDATION.md`
before trusting the headline number. Additional caveats:
- the 2018-19 small-cap bust sits inside the training window; over the full 2017->2026 period the
  same configuration shows 19.9% time-weighted CAGR with a -46% drawdown, not 28.7%/-22.2%;
- the boom years 2021 and 2023 carry much of the out-of-sample excess;
- fundamentals survivorship bias: delisted names keep their price history but never had a
  screener.in page, so Sleeve L's fundamentals exist only for survivors — 823 of the 1,225 names
  in the 2017-21 universe. Sleeve S (price-only) does not carry this bias;
- the base configuration's full-period result was seen once before the protocol ran; the engine
  bugs that pass found and fixed are listed in the design spec §4.2.

**Sleeve S: DIAGNOSTIC** (claim-state ladder step 1 of 4). OOS Sharpe -0.22, IR -0.92,
deflated-Sharpe p = 0.855; turnover ~2,000%/yr drives costs to 1,180-1,360 bps/yr, which erases
any signal the weekly design has. It is never exposed to Project Upstox as anything but a
diagnostic line. An exploratory, post-hoc minimum-hold rule improved turnover sharply but still
only matched the index after costs; the next pre-registered experiment is 8-12 week holds with a
signal that actually clears the cost line. Full fold-by-fold detail for both sleeves: `docs/VALIDATION.md`.

## The advisor contract (for Project Upstox, later — R6)

`GET /advisor/v1/evidence/{symbol}`, bearer token `EQR_ADVISOR_TOKEN`. The response carries each
sleeve's rank/percentile/`validated` flag, flags, an optional dossier summary line, and a
`status` of `OK | STALE | UNKNOWN`. The reference client (`eqr/surfaces/advisor_client.py`, the
code Upstox would copy) is fail-soft by construction: any transport error, non-200, STALE or
UNKNOWN status returns `None`, and the caller must treat that as an UNKNOWN check — it can add at
most one line's worth of points and never removes a gate Upstox already has. This integration is
out of scope until a sleeve exists behind a real, reachable API, and is tracked as Upstox's own
R6 phase — nothing in this repo calls into Upstox, and nothing in Upstox calls into this repo
today.

## Guardrails

- No order path anywhere in this repo. Sizing produces target weights only.
- Dossiers never change ranks. Every claim in a dossier must cite a `[doc_id]` or a named table;
  a dossier with an unsupported claim fails validation and the run is rejected outright, never
  partially stored.
- `data/` is gitignored (DuckDB file, raw archives, PDFs) — never committed.
- Secrets live only in `.env` (never `.env.example`, never a doc). Env-var names only, in
  `docs/REBUILD_SPEC.md`.
- The OCI box is Upstox-only; this project is never deployed there. Its own VM (when it exists)
  is a separate Hetzner or GCP box.
- Every git push, deploy, env change and DB migration goes through `production-engineer`; every
  doc goes through `documentation-engineer`. Neither is done by hand.

## Docs map

`docs/DOCS_INDEX.md` (full map) · `docs/REBUILD_SPEC.md` (rebuild from zero) ·
`docs/DATA_SOURCES.md` (every source, cadence, PIT rule, failure mode) ·
`docs/OPERATIONS.md` (runbook, quality checks, dossiers, open items) ·
`docs/VALIDATION.md` (protocol, acceptance bar, both sleeves' fold tables) ·
`docs/superpowers/specs/2026-09-14-research-bot-design.md` (the approved design spec — read this
first for anything not covered above) · `docs/superpowers/plans/2026-09-14-research-bot-plan.md`
(the build plan).
