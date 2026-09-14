# Sumaer Research Bot (`eqr`) — Design Spec

Date: 2026-09-14 · Status: approved to build (Approach A, spine-first, strict layers) · Owner: Sumaer Bahl

## 1. Purpose

An independent Indian-equity research system that (a) ranks the full NSE universe with a
point-in-time (PIT) quantitative engine whose edge is measured before it is trusted, and
(b) writes Claude research dossiers on request, grounded in stored filings. It advises
Project Upstox through a read-only API as one fail-soft evidence line; it never places
orders and never bypasses Upstox gates.

Non-goals: order execution, intraday data, options, paid data feeds, any change to the
Upstox repo or the OCI box.

## 2. Requirements (from the brainstorm)

| Question | Decision |
|---|---|
| Output | Both quantitative ranks and Claude dossiers, quant-first |
| Universe | All NSE-listed equities (~2,000 EQ-series names) |
| Horizon | Two separate sleeves: L (months, monthly rebalance) and S (weeks, weekly) |
| Budget | Data spend unconstrained; Claude runs on request only |
| Runtime | New non-OCI VM; Mac for Claude runs; local dev on the Mac |
| Surfaces | Light web dashboard, Telegram digest, read-only advisor API, dossiers |

## 3. Architecture

Python 3.13 package `eqr` (CLI `eqr`). One repo, strict layers; the contract between
layers is DuckDB tables with documented schemas. A layer never calls another layer's
fetchers.

```
eqr/store      DuckDB file data/eqr.duckdb; schema.sql; upsert helpers; PIT helpers
eqr/spine      fetch -> data/raw (immutable) -> curated tables; quality harness
eqr/features   cross-sectional factor engine (reads curated, writes features_monthly)
eqr/strategy   regime, two sleeves, sizing, rank
eqr/validate   costs, backtest, walk-forward, metrics, acceptance bar, reports
eqr/research   document store, dossier packs, Claude invocation, dossier schema
eqr/surfaces   FastAPI web + advisor API, Telegram digest
```

Code copied from Project Upstox (copies, never a shared tree): fundamentals models,
OHLCV helpers, NSE session warm-up, screener parser skeleton, Telegram sender.

### 3.1 Hosting

Default Hetzner CX32 (4 vCPU / 8 GB / 80 GB, ~EUR 7/mo) or GCP e2-standard-2 Mumbai if an
Indian IP is preferred. Ubuntu 24.04, `uv`-managed Python, systemd timers, Caddy TLS.
Nightly `restic` backup of `data/` to Backblaze B2. Claude never runs unattended on the
VM: `eqr dossier SYMBOL` runs on the Mac, pulls the pack from the VM API, calls Claude,
posts the dossier back. The VM is provisioned by Sumaer (account + payment); `deploy/`
carries an idempotent `install.sh`, units and Caddyfile so the box is reproducible.

Until the VM exists, the same stack runs on the Mac (`eqr web`, `eqr refresh`).

### 3.2 Point-in-time rules (the spine's law)

Every curated row carries `as_of` (the date the fact describes) and, where the fact
becomes known later than it is dated, `visible_from` (the first date a strategy may use
it). Readers ask `as_of_view(table, date)` and never see rows with `visible_from > date`.

| Table | as_of | visible_from |
|---|---|---|
| prices_daily, index_daily | trade_date | same day (published after close) |
| adj_factors | ex_date | ex_date |
| statements (quarterly, annual) | period_end | NSE filing date when known; else period_end + 45 d (Q1–Q3) / + 60 d (Q4 and annual) |
| shareholding | quarter end | quarter end + 21 d (SEBI deadline) |
| surveillance, fo_ban, deals | list date | same day |
| documents | publish date | publish date |

Restatements: screener.in shows latest restated numbers. We store each fetch with
`fetched_at` and keep the FIRST-seen value per (symbol, stmt, period_end, line_item) as
the PIT value; later fetches are stored as revisions (`statement_revisions`). Before the
first fetch date, history is as-restated — a known, documented bias.

Filing dates come from two NSE feeds (legacy `corporates-financial-results` to early 2025,
`integrated-filing-results` from 2025); 84% of quarterly statements since 2016 carry a real
filing date (median lag 42 days), the rest use the +45/+60-day rule. screener carries 13
quarters and 12 fiscal years: before mid-2023 the trailing metrics fall back to the last
visible fiscal year (`stmt_age_days` shows the staleness).

Known survivorship bias (open item): delisted names have prices (the archive keeps them)
but no screener page, so Sleeve L's fundamentals exist only for survivors — 823 of the
1,225 names in the 2017–21 universe. Sleeve S (price-only) is free of it. Closing it means
fetching statements for the ~450 delisted names by BSE code.

## 4. Data spine

### 4.1 Sources (all public, personal use, ≤ 1 req/s, cached raw)

| Source | What | Cadence | Notes |
|---|---|---|---|
| NSE archives `sec_bhavdata_full_DDMMYYYY.csv` | OHLC, VWAP, volume, turnover, trades, delivery | daily EOD | from ~2020; verified 2026-09-11 |
| NSE archives `cmDDMONYYYYbhav.csv.zip` + `MTO_DDMMYYYY.DAT` | same minus VWAP/trades; delivery from MTO | backfill 2016–2020 | verified 2010→ and 2016→ |
| NSE archives `ind_close_all_DDMMYYYY.csv` | all index closes incl. NIFTY 500, India VIX, P/E, P/B, div yield | daily | verified 2014→ |
| NSE archives `EQUITY_L.csv`, `ind_nifty500list.csv`, `fo_secban.csv`, `bulk.csv`, `block.csv` | instruments (face value, listing date), index list + industry, F&O ban, deals | daily snapshots | no cookies |
| NSE API (cookie warm-up) | corporate actions, financial-results filing dates, announcements (PDF links), ASM/GSM/ESM lists, shareholding, annual reports | daily / on demand | verified 200 from this Mac; 403 on datacenter IPs handled by SOCKS proxy fallback |
| screener.in company pages | 12 y annual P&L/BS/CF/ratios, 13 quarters, shareholding, results PDF links | weekly sweep + daily for names with fresh results | regex over landmark sections; page change degrades to a quality flag, never a crash |

### 4.2 Price adjustment (corporate actions confirmed on the tape)

Verified during the build (2026-09-14): NSE bhavcopies do NOT restate `PREV_CLOSE` on
ex-dates (RELIANCE 28-Oct-2024 bonus: prev 2,655.70, open 1,337.00), so the tape alone
cannot label events. The source of record is the NSE corporate-actions feed: the subject
text yields the factor (bonus a:b → b/(a+b); split Rs X→Y → Y/X; consolidation X→Y →
Y/X), and each action is CONFIRMED by the ex-date open gapping by roughly that factor
(±35%), searching ±3 sessions; unconfirmed actions are recorded in `factor_anomalies`
and not applied. A secondary scan catches clean-ratio gaps (1/2, 1/5, 1/10 …) that persist
for three sessions with a matching jump in traded volume and no action on file (ETF
splits, small caps missing from the feed); sub-₹5 names are excluded (tick artefacts).
Rights and ordinary dividends are not adjusted. Result on 2016→2026: 707 confirmed
actions + 67 gap-inferred; 44 anomalies.

Other spine facts learned during the build: NSE holds weekend sessions (Budget
Saturdays, Muhurat Sundays, DR-drill Saturdays) — ten were found and loaded; NSE also
republishes Friday's `sec_bhavdata_full` under Sunday filenames in 2019–21, so the loader
trusts the date inside the file, never the URL; the `ind_close_all` file occasionally
carries a stray row dated another day, so index rows are filtered to the file's date;
stocks move between the EQ and BE/BZ series during surveillance, so the price panel is
continuous across series while eligibility is judged on EQ only; ETFs trade in the EQ
series and are excluded via `eq_etfseclist.csv`.

### 4.3 Universe (PIT, liquidity-defined)

For as-of date d: symbols with series EQ traded on d, ≥ 250 sessions of history, close
≥ ₹20, median 120-day traded value ≥ ₹1 cr (Sleeve L) / ₹3 cr (Sleeve S), not in GSM or
ASM stage ≥ 2, not in F&O ban. No index-membership lookups, so no survivorship bias:
delisted names remain in history because the bhavcopy archive is the source.

### 4.4 Quality harness

After every refresh: bhavcopy EQ rows within [1,500, 3,000]; no duplicate keys; NIFTY 50,
NIFTY 500 and India VIX present; price jumps > 50% without an adjustment factor flagged;
delivery coverage ≥ 90% of EQ rows; statements freshness (share of universe with a
statement visible in the last 120 days); every fetch logged with status and bytes. Failed
checks go to `quality_checks` and to the Telegram digest.

## 5. Feature engine

`build_features(as_of)` computes, for every universe name, from data visible at `as_of`:

- Price: mom_12_1, mom_6_1, mom_1 (reversal), vol_60, vol_250, dd_250, dist_52w_high,
  dma50_ratio, dma200_ratio, atr14_pct, adv20_inr, turnover_med120, deliv_pct_20,
  deliv_ratio (20 d / 120 d), amihud_60, beta_250 and idio_vol_250 vs NIFTY 500.
- Fundamentals (as-of statements): sales_ttm, pat_ttm, sales_yoy_ttm, pat_yoy_ttm,
  sales_cagr_3y, opm_ttm, opm_chg_1y, roe, roce, debt_equity, int_cover, accruals
  ((PAT − CFO)/TA), fcf_yield, promoter_pct, promoter_chg_1y, inst_chg_1y, f_score
  (partial, 6 of 9 signals available from screener data), altman_zpp (approximation:
  EBIT = OP − Dep + other income; TL = borrowings + other liabilities; WC = other assets −
  other liabilities).
- Valuation: shares = equity_capital / face_value (split-consistent), mcap, pe_ttm, pb,
  ps, earnings_yield, dividend_yield.

Cross-section: winsorise each raw factor at ±3 MAD, z-score within industry (fallback:
whole universe when an industry has < 8 names), then average into four buckets: quality,
value, momentum, low-risk. UNKNOWN stays NULL and is excluded from the bucket mean; a name
with fewer than 2 of 4 buckets known is not rankable.

## 6. Strategy

### 6.1 Regime

NIFTY 500 close vs its 200-DMA and India VIX 1-year percentile:
RISK_ON (above DMA and VIX pct < 80) → exposure 1.0; NEUTRAL (one of the two) → 0.7;
RISK_OFF (below DMA and VIX pct ≥ 80) → 0.4. Remainder is cash at the risk-free rate.

### 6.2 Sleeve L — Compounders (monthly)

Score = 0.30 quality + 0.25 value + 0.30 momentum + 0.15 low-risk (bucket z-scores).
Filters from §4.3 plus pat_ttm > 0. Top N = 30, rank hysteresis (a holding stays while
inside the top 45). Signals use the last close of the month; execution at the next
session's open.

### 6.3 Sleeve S — Tactical (weekly)

Score = 0.40 mom_1 + 0.30 breakout (dist_52w_high ≥ −5% and volume 20 d / 120 d ≥ 1.5)
+ 0.30 delivery surge (deliv_ratio z). RISK_OFF → no new entries. Top N = 20, hold while
inside the top 30, hard stop at −8% from entry (exit at next open). Weekly on the last
session of the week.

### 6.4 Sizing

Inverse 60-day volatility within the sleeve, capped 5% per name and 25% per industry,
scaled by the regime exposure. Both sleeves emit target weights; execution is out of scope.

## 7. Validation protocol (pre-registered)

Cost model (Indian delivery equity): STT 0.1% each side; exchange 0.00297%; SEBI ₹10/cr;
stamp 0.015% buy; GST 18% on brokerage+exchange+SEBI; brokerage ₹0 (discount) or ₹20 per
order flat, configurable; DP charge ₹15.34 per sell scrip-day; impact = 10 bps + 25 bps ×
sqrt(order_value / ADV20), capped at 100 bps. Costs are computed per order on a stated
capital base (default ₹10 lakh; the ₹70k shadow case is reported separately).

Backtest: signal at close of t, fill at open of t+1, MTM equity daily from adjusted
closes, delisted names exit at their last close with a 100 bps haircut, dividends not
credited (conservative versus the TR benchmark).

Walk-forward: expanding folds, one per calendar year 2019–2025, purge one holding period
at each boundary and embargo one month. The last 12 months (2025-09 → 2026-08) are a
holdout evaluated once at the end. Trials counted for deflated Sharpe: N ∈ {20, 30} × 3
weight variants = 6 per sleeve.

Acceptance bar (all must hold, net of costs, OOS): Sharpe ≥ 0.8; IR ≥ 0.5 vs NIFTY 500 TR
(price index + 1.3% assumed yield, documented); MTM max drawdown ≤ the index's; deflated
Sharpe p < 0.05; positive excess in ≥ 3 of 4 most recent folds; robust across universe
thresholds (₹1 cr / ₹3 cr) and N ∈ {20, 30}; capacity: median order < 5% of ADV20 at ₹10
lakh. A sleeve that fails is reported as NOT VALIDATED and is never exposed to Upstox
as anything but a diagnostic line.

Benchmarks: NIFTY 500 (proxy TR), NIFTY 50, equal-weight universe.

## 8. Research layer (Claude dossiers)

- Document store: NSE announcements filtered to results, investor presentations, concall
  transcripts, annual reports; PDFs under `data/docs/<symbol>/`, text extracted with
  pypdf into sidecars; metadata in `documents` with sha256 and `visible_from`.
- Pack: `eqr pack SYMBOL --as-of` writes a JSON pack (facts, features, ranks, 8 quarters,
  5 years, shareholding, surveillance, deals, peers) plus text excerpts of the latest
  transcript and results filing, every excerpt tagged `[doc_id]`.
- Dossier: `eqr dossier SYMBOL` builds the pack, invokes Claude (Claude Code CLI on the
  Mac, or the API when `ANTHROPIC_API_KEY` is set), validates the JSON block against
  `eqr/research/schema.json`, stores JSON + Markdown in `dossiers`. Every claim must cite
  a `[doc_id]` or a named table; unsupported claims fail validation and the run is
  rejected, not partially stored.
- Guardrails: dossiers never change ranks; the advisor API carries the dossier only as a
  summary line with its date; no LLM output reaches any order path.

## 9. Surfaces

- Web (FastAPI + Jinja2, light theme, no JS framework): dashboard (regime, data
  freshness, top ranks per sleeve, last backtest verdict), symbol page (features,
  statements, adjusted price chart as inline SVG, dossier), ranks, backtests, health.
- Advisor API: `GET /advisor/v1/evidence/{symbol}` with bearer token. Response:
  `{symbol, as_of, regime, sleeve_L: {rank, universe_size, score, validated}, sleeve_S:
  {...}, flags: [], dossier: {as_of, rating, confidence} | null, freshness_days, status:
  OK | STALE | UNKNOWN}`. Contract for Upstox (later, R6): any non-200, STALE or UNKNOWN
  is treated as UNKNOWN evidence; the line can add at most one check's points and never
  removes a gate.
- Telegram digest 07:30 IST: regime, entries/exits since yesterday per sleeve, results due
  today, data-quality failures. Send-only bot; dry-run prints.

## 10. Error handling

Fetchers never raise past the refresh orchestrator: each step returns a `FetchResult`
(status ok/missing/blocked/error, bytes, error text) logged to `fetch_log`. Missing
archives on a weekday after 19:00 IST are retried next run; a 403 storm triggers proxy
fallback and a digest warning. Parsers reject a file with the wrong column set rather
than guess. Features skip names with missing inputs (NULL, never zero). Backtests refuse
to run over a date range with quality failures unless `--force`.

## 11. Testing

pytest per layer with fixtures: three bhavcopy formats, MTO, index CSV, a screener page
snippet, synthetic price panels with a known split, synthetic factor panels with a
planted signal (the backtest must recover it), deflated-Sharpe known values, cost-model
hand-computed orders, API contract tests with FastAPI TestClient, dossier schema
validation with a good and a bad fixture. Live smoke: `eqr doctor` fetches one file per
source and reports.

## 12. Security and ops

Secrets only in `.env` (Telegram token, advisor token, proxy URL, optional API key);
`.env.example` lists names. Advisor API bound behind Caddy with bearer auth; web UI is
read-only. `data/` is gitignored (raw archives, DuckDB, PDFs). Deploy, env and push
through production-engineer; docs through documentation-engineer; registry entry
`research-bot` (model data-only until the VM exists).

## 12a. Validation outcome (2026-09-14, first run of the pre-registered protocol)

Sleeve L: VALIDATED. Stitched OOS 2019→Aug-2025, net of costs: CAGR 28.7% vs 17.1%
(NIFTY 500 TR proxy), Sharpe 1.28 vs 0.73, MTM maxDD −22.2% vs −37.8%, IR 0.72, deflated
Sharpe p = 0.005 (6 trials), 4 of 4 recent folds positive, robust across N ∈ {20, 30} and
₹1/3 cr floors, median order 0.03% of ADV20 at ₹10 lakh. Holdout Sep-2025→Sep-2026:
21.9% vs 1.9%, Sharpe 0.98. The selected configuration is N=20 momentum-tilt. Caveats
carried with the verdict: the 2018–19 small-cap bust sits in the training window (full
period 2017→2026 the same configuration shows 19.9% CAGR with a −46% drawdown); the
boom years 2021 and 2023 carry much of the OOS excess; the fundamentals survivorship bias
above; and the base configuration's full-period result was seen once before the
protocol ran (engine bugs found and fixed in that pass are listed in 4.2).

Sleeve S: NOT VALIDATED. OOS Sharpe −0.22, IR −0.92, DSR p = 0.86; turnover ~2,000%/yr,
costs ~1,180 bps/yr. The weekly design churns the whole book every week. One exploratory
(post-hoc, NOT validated) run of a hold-period rule — minimum 20 sessions, hold while
inside 3N, no trims — over 2019→2026 moved the N=20 flow-tilt variant from Sharpe 0.01 to
0.61 and turnover from 2,071% to 926%, but only matched the index (CAGR 15.3% vs 14.0%,
IR 0.06) with 469 bps/yr of costs. Next pre-registered experiment: 8–12 week holds and a
signal that survives the cost line; until then Sleeve S is a diagnostic list only.

Both reports live under `data/reports/validate-*/` and in the `backtests` table.

## 13. Build order

1. store + schema + PIT helpers · 2. spine: archives, adjustment, universe, quality,
backfill 2016→ · 3. NSE API + screener fundamentals + results calendar ·
4. features · 5. strategy · 6. validation + reports (run for real) · 7. research layer ·
8. surfaces · 9. deploy artefacts · 10. docs, registry, push.

## 14. Out of scope (v1)

Intraday data, F&O, consensus estimates (no free Indian source), BSE-only names, XBRL
parsing, Beneish M (screener lacks 3 of 8 components), Upstox-side fetcher (R6 after
validation), automatic Claude runs.
