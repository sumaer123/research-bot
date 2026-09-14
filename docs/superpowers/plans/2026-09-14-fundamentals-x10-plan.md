# Sumaer Research Bot — Fundamentals ×10 Implementation Plan

**Status:** approved by Sumaer on 2026-09-14 (plan mode). **Project:** `Downloads/Sumaer's Claude Data/Project Research Bot` (package `eqr`). **Companion documents:** `docs/superpowers/specs/2026-09-14-research-bot-design.md` (the original design), `docs/VALIDATION.md` (sleeve verdicts). **Execution:** superpowers subagent-driven development, one task per fresh subagent, tests per task, commits per task; pushes/deploys via production-engineer, docs via documentation-engineer.


Project: `Downloads/Sumaer's Claude Data/Project Research Bot` (package `eqr`, DuckDB point-in-time store, Python 3.13 venv via uv, 45 tests). Repo `sumaer123/research-bot`, registry key `research-bot`, Mac launchd agents live on :8801.

## 1. Context

**Why.** The bot is a strong *quant* engine (PIT NSE + screener.in spine 2016→, cross-sectional factors, Sleeve L walk-forward VALIDATED: OOS CAGR 28.7% vs 17.1%, Sharpe 1.28, DSR p 0.005). Its *fundamental research* is thin: screener aggregates only (no receivables, inventory, employee cost, contingent liabilities, segments, auditor, related parties), no insider/pledge/credit-rating feeds, annual reports and concalls reduced to a 12,000-character excerpt, no news or web, no valuation model, no company-relationship data, and the only "rating" is whatever Claude writes into a dossier. Sumaer asked for a plan to make the bot 10× better at (1) capturing comprehensive fundamental analytics, (2) very comprehensive independent research on any stock, using internet sources, (3) a big fundamental knowledge graph, and (4) a final rating with a Buy/Hold/Sell verdict.

**Decisions taken with Sumaer (2026-09-14).** Claude through the official Anthropic SDK (Opus 5; server-side web search; Batches for the weekly run). Free web sources only (no Parallel.ai). Coverage: nightly deterministic rating for every rankable name (no LLM), weekly LLM research for held names plus the top 40 of Sleeve L, on-demand deep research for any symbol.

**Principles (from the existing spec, extended).** PIT law on every new table (`as_of` + `visible_from` from the feed's broadcast/filing date, never fetch time; first-seen wins; revisions logged). No LLM output changes sleeve ranks or reaches any order path. The rating is produced by a deterministic, versioned engine (xirr-engine pattern: DATA_ERROR gate, manifest of every input, no LLM in the compute path); Claude contributes only capped, cited, verified structured inputs. Never zero-fill; UNKNOWN lowers confidence, not the score. Light white UI, Jinja2 + inline SVG, no JS framework. Every new signal is calibrated before it is labelled validated. Git pushes, deploys, env changes go through production-engineer; `.md` docs through documentation-engineer.

## 2. Evaluation of the current bot

Verified in code (agents read every module) and, for the data facts, by read-only probes on 2026-09-14 (nothing written to `data/`):

| Area | Today | Gap |
|---|---|---|
| Statements | `eqr/spine/screener.py`: 12y annual + 13q aggregates (1.02M rows, 2,294 cached pages); `visible_from` = NSE filing date (84%) else +45/+60d | No line-item detail → no Beneish, no forensic ratios, no segments; 333 filing symbols since FY2018 are absent from `instruments` (delisted/renamed, inferred) so their fundamentals never existed |
| Filings | `eqr/spine/nse_api.py`: corporate actions, results calendar (legacy + integrated feed), ASM/GSM/ESM, aggregate shareholding, announcements, annual-report list | No insider trades, pledge, credit ratings, board meetings, named holders. Both results feeds already return an `xbrl` URL per filing that the loader drops |
| Documents | `eqr/research/docstore.py` (14 PDFs stored, pypdf text sidecars), `pack.py` sends ≤ 4 docs × 12,000 chars | No section structure or tables; most of an annual report never reaches the model. pypdf text quality measured good on transcripts (0.90–0.93 prose-line share) and annual reports (0.69, 97–112 section-heading hits); image-only presentations extract nothing |
| Factors | `eqr/features/fundamental.py` (~30 fundamentals, 7-signal Piotroski, Altman Z'') + `xsection.py` (MAD winsorise, industry z-scores, 4 buckets) | Fit for ranking, not for judging a company: no earnings-quality battery, valuation model, governance events or sector KPIs |
| Research | `eqr/research/dossier.py`: one Claude call via raw HTTP or `claude -p`; strict schema; every claim cites `doc:`/`table:`; all-or-nothing | Single pass, no web/news, no verifier, the model writes the rating itself, `dossiers` has 0 rows |
| Rating | none | No deterministic, calibrated, explainable rating; nothing nightly |
| Relationships | `instruments.industry` + 8 screener peers | No promoter/group/auditor/rating-agency/subsidiary graph |
| Surfaces | FastAPI :8801, advisor API, Telegram digest | No rating, forensic, valuation or graph views |

Reusable assets (ported into `eqr` with tests, never imported across projects): Project Upstox `upx/fundamentals.py` (hand-verified Piotroski 9, Altman Z'' EM, Beneish M with the paper's 4.679 TATA coefficient, Sloan accruals, abstention rules), `upx/scoring.py` (layered score, hard gates, confidence separate from score, adverse-keyword table), `upx/news.py`; xirr-engine (DATA_ERROR gate + manifest); DobbyNXT edge conventions (evidence, valid_from/valid_to, confidence, derived_by; edge identity = src/type/dst/evidence).

**Live-feed facts that shaped the design** (observed unless marked inferred; probes ran from the Mac's residential IP with the existing cookie warm-up):
- Both `corporates-financial-results` and `integrated-filing-results` rows carry `xbrl` URLs on `nsearchives.nseindia.com`. Real XBRL exists from Q4 FY2018 (2016–17 rows hold a `/-` placeholder). 106,825 distinct filings since 2018-03-31 in `results_calendar` (≈ 5 GB and ≈ 30 h at 1 req/s are inferred, not measured).
- Three taxonomy namespaces (`in-bse-fin` 2018-03-31 and 2020-03-31, `in-capmkt` 2026-01-31) plus a bank variant (`in-capmkt-ent`); core P&L tags are stable across them. Half-yearly/annual files carry the balance sheet, cash flow, `AuditorsFirmName` and the unmodified-opinion declaration; bank files carry CET1, GNPA %, NPA %, ROA, provisions.
- `/api/corporate-pledgedata` returns empty `data` in every parameter shape → pledges must come from the shareholding-pattern XBRL (`SHP_*.xml`, `in-bse-shp`), which carries `NameOfTheShareholder`, share counts, percentages and the promoter pledge flag; the per-holder pledged-count tag is not yet observed (spike on a pledged name).
- `/api/corporates-pit` (insider trading) ignores date windows; latest 20 per symbol works → forward-only ledger, no backfill.
- `/api/corporate-credit-rating` is a market-wide feed (symbol filter ignored) with ISIN, rating, action, outlook, earlier rating, `XbrlFileName`, `AppID`; many rows are `NOTLISTED` debt issuers; history begins between Apr and Sep 2023.
- `/api/corporate-board-meetings` works per symbol and market-wide with date windows.
- Anthropic document `citations` are incompatible with structured outputs (400 per the bundled `claude-api` skill) → claims carry verbatim quotes that are verified deterministically instead.
- venv has `lxml`, `pydantic`, `bs4`; lacks `anthropic`, `networkx`, `feedparser`, `pdfplumber`, `docling`. PyPI JSON was SSL-blocked from `requests`; `uv` resolution is the spike.

External evidence used: Kim–Muhn–Nikolaev (LLM statement analysis; paper withdrawn pending replication → deterministic core, LLM capped); TradingAgents / ai-hedge-fund (role separation, structured signals, short backtests → we calibrate ourselves); Ambit HAWK and Marcellus forensic frameworks (the check list in §3.4); Feng et al. 2019 and Cohen–Frazzini (relation features are worth testing, not assuming); Damodaran India ERP/beta/WACC files (updated each January); Kuzu archived 2025-10-10 (not adopted); duckpgq research-grade (not required).

## 3. Design

### 3.1 Architecture (new subpackages, same layering; `tests/test_layering.py` proves `spine`/`features`/`strategy` never import `rating`/`research`/`graph`/`anthropic`)

```
eqr.store        + statements_xbrl, xbrl_filings, credit_ratings, board_meetings, insider_trades, holders_named, pledges,
                   doc_sections, fund_metrics, graph_nodes, graph_edges, graph_aliases, graph_features,
                   ratings, rating_ledger, rating_calibrations, research_runs, dossier_claims, web_sources, news_items
                   (+ migrations.sql: ADD COLUMN IF NOT EXISTS on results_calendar, documents, dossiers)
eqr.spine        + xbrl.py, nse_filings.py; nse_api.py keeps xbrl_url/seq_id/type_sub; quality.py + 3 checks
eqr.fundamentals NEW base.py, forensic.py, quality.py, valuation.py, governance.py, sector_kpis.py, build.py
eqr.rating       NEW pillars.py, engine.py (pure), ledger.py, calibrate.py, acceptance.py, report.py
eqr.research     + docparse.py, news.py, llm.py, verify.py, research.py; pack.py v2; schema.json v2; dossier.py kept as v1 wrapper
eqr.graph        NEW model.py, store.py, builders.py, features.py, export.py, layout.py
eqr.surfaces     + /ratings, /graph, /doc/{id}, symbol Research section, advisor `rating` block, digest lines
deploy/mac       refresh/fundamentals chains extended; new com.eqr.research (Sunday 03:00)
```

Nightly flow: refresh → filings (daily window) → XBRL (recent) → `rate --universe --publish`. Weekly (Sat 02:00): screener sweep → insider sweep → features → `metrics` → docs parse (recent) → graph build + features → ranks → rate. Sunday 03:00: research batch (held + top 40) → collect. On demand: `eqr research SYMBOL [--deep]`.

### 3.2 Data spine expansion (Phase 1)

| Source | Module / table | PIT rule | Notes |
|---|---|---|---|
| XBRL results (quarterly P&L detail; half-yearly/annual balance sheet, cash flow, auditor, opinion, segments; bank KPIs) | `spine/xbrl.py` → `xbrl_filings`, `statements_xbrl` (+`_revisions`) | `visible_from = filing_dt` (exact) | URL from both results feeds; raw archive `nse/xbrl/<symbol>/<period>_<basis>_<sha>.xml`; tag map per namespace in `canonical_item()`; crore scaling from the rounding tag, cross-checked against screener FY sales (`xbrl_screener_agreement` quality check); unknown tags stored raw, never guessed; backfill 2018→ runs in the background over nights |
| Credit ratings (market-wide daily feed, from ~Sep 2023) | `spine/nse_filings.py` → `credit_ratings` (`app_id` PK, `notch` from a rating→rank map, ISIN-first then normalised-name match to `symbol`) | `visible_from = broadcast date` | Unmatched debt issuers keep `symbol NULL`; rationale PDFs continue to arrive through announcements (kind `rating`) |
| Board meetings | same → `board_meetings` (purpose kind: results / dividend / fund_raise / other) | intimation date | market-wide daily window |
| Insider trades (PIT 7(2)) | same → `insider_trades` | intimation date | latest 20 per symbol, first-seen ledger; universe sweep weekly |
| Shareholding-pattern XBRL | same → `holders_named` (promoter names, share counts, %, locked-in), `pledges` (promoter-level; per-holder counts if the spike finds the tag) | broadcast date | 8 quarters per symbol; feeds the promoter-group graph |
| News | `research/news.py` → `news_items` | published date | Google News RSS via feedparser, sha1 dedupe, fail-soft |
| Valuation inputs | `config.py`: `EQR_ERP_PCT` (Damodaran India ERP) + existing `EQR_RISK_FREE_PCT`; `beta_250` from features | — | Damodaran's `betaIndia`/`waccIndia` files are the January source for the two numbers; no macro table (YAGNI) |

### 3.3 Documents (Phase 4)

Default parser = pypdf (layout mode, already stored) + regex section locator (`SECTION_PATTERNS`, kinds: `auditor_report`, `caro`, `contingent_liabilities`, `rpt_note`, `borrowings_note`, `segment_note`, `mdna`, `directors_report`, `aoc1_subsidiaries`, `remuneration`, `board`, `top_holders`, `concall_prepared`, `concall_qa`, `rating_rationale`) + `pdfplumber` tables only on the ≤ 15 located pages → `doc_sections` (text, tables_json, page range, method, confidence). Deterministic note extractors: contingent-liabilities total, auditor remuneration, related-party totals, subsidiary list. docling is an optional extra for image-heavy presentations only, gated on spike S0.8. `%PDF` magic check and `extract_status` are added to the docstore.

### 3.4 Fundamental analytics (Phase 2) — `eqr/fundamentals/`

`Metric(name, value|None, status OK/UNKNOWN/NA, unit, source_table, source_keys, inputs_as_of, note)`; `build_metrics(con, as_of)` writes long-format `fund_metrics` (as_of, symbol, metric, value, status, provenance, engine_version) monthly and nightly for the latest date. Percentiles reuse `features/xsection.py::winsorise` and the industry-then-universe grouping rule (≥ 8 names).

- **forensic.py** (Ambit-style, multi-year medians, universe deciles): CFO/EBITDA 5y, cumulative FCF/median sales 6y, cash yield, depreciation-rate CV, contingent liabilities/net worth, auditor-fee vs revenue CAGR gap, CWIP/gross block, other-expenses ratio delta, reserves leakage vs retained PAT, provisioning vs receivables, related-party advances/CFO, debtor-days delta; Beneish M (8 variables, abstains below 6 real components), Sloan accruals, Mohanram G (partial). Banks/NBFCs: GNPA trend, provision coverage, credit cost, cost-to-income (Marcellus-style).
- **quality.py** (QMJ structure): ROCE median/min 10y, ROE TTM, OPM CV 8y, CFO/PAT 5y, incremental ROCE 5y, net debt/EBITDA, Altman Z'', F-score ratio, reinvestment rate, payout 5y; bank ROA, NIM proxy, CET1, deposit growth.
- **valuation.py**: earnings/FCF yield, EV/EBIT, P/E and EV/EBIT position in own 10y band, P/B vs justified P/B (financials), reverse-DCF implied growth (`wacc()` from beta/rf/ERP, 10y two-stage, terminal 5%) and `growth_gap` = implied − delivered, dividend yield, expected-return band (informational only, never a score input).
- **governance.py**: pledged % of promoter holding, pledge delta 4q, insider net buying 12m / mcap, promoter and institutional 1y change, auditor change 24m, audit opinion modified, rating migration 12m (notches), negative outlook, adverse announcements 90d (ported keyword table), surveillance flag, promoter-entity count; `board_independence` and `rpt_scale_to_revenue` UNKNOWN until documents supply them.
- **sector_kpis.py**: bank/NBFC KPIs from XBRL; other sectors UNKNOWN (no invented numbers).

### 3.5 Rating engine (Phase 3) — `eqr/rating/engine.py`, pure and versioned

Engine versions are calibrated separately like sleeves: **r1** (screener + features + shareholding + surveillance, calibratable from 2017 on day one), **r2** adds the Forensic pillar from XBRL (from 2019), **r3** adds Graph-risk and Qualitative.

Component score = 100 × percentile of `sign × winsorised value` within industry (≥ 8 names) else universe; level components use fixed maps; binaries 0/100; UNKNOWN has no score. Pillar = weighted mean over known components; UNKNOWN when < 50% of applicable component weight is known.

| Pillar | Weight (base) | Components (sign); financial variant in brackets |
|---|---|---|
| Quality | 0.20 | roce_median_10y +, roe_ttm +, opm_cv_8y −, cfo_to_pat_5y +, incremental_roce_5y +, net_debt_to_ebitda −, altman_zpp +, f_score_ratio +, reinvestment_rate_5y + [roa, nim_proxy, cost_to_income −, cet1, gnpa −, roe] |
| Forensic (r2) | 0.15 | beneish level (clean 100 / watch 50 / flag 0, weight 2), sloan −|x|, cfo_to_ebitda_5y +, reserves_leakage −, cwip_to_gross_block −, other_expenses_delta −, debtor_days_delta −, depreciation_cv −, contingent_liab −, auditor_fee_gap −, rpt_advances −, mohanram + [gnpa_trend −, provision_coverage +, credit_cost −, cost_to_income −] |
| Growth | 0.10 | sales/pat CAGR 3y +, TTM YoY sales/pat +, eps_cagr_5y +, growth_consistency_5y + [+ advances, deposits growth] |
| Valuation | 0.20 | earnings_yield +, fcf_yield +, ev_ebit −, pe_band_pos_10y −, ev_ebit_band_pos −, growth_gap −, div_yield + [earnings_yield, pb_vs_justified −, pe_band −, div_yield] |
| Governance | 0.15 | pledge level map (0→100, ≤10→80, ≤25→50, ≤50→20, >50→0), pledge_delta −, insider_net_buy +, promoter_chg +, inst_chg +, auditor_change (binary), audit_qualified (binary), rating_migration +, outlook_negative (binary), adverse_events_90d (binary), surveillance (binary), board_independence +, rpt_scale − |
| Momentum | 0.10 | mom_12_1 +, mom_6_1 +, dist_52w_high +, dma200_ratio +, deliv_ratio +, idio_vol_250 −, amihud_60 − |
| Graph risk (r3) | 0.05 | 100 − penalties: group_pledge_max (level map, weight 2), group_surveillance, group_downgrades_12m, auditor_qualified_share_24m, auditor_small, sector_downgrade_share_12m |
| Qualitative (r3) | 0.05 (asserted ≤ 0.20) | mean of verified dossier grades (management, moat, capital allocation, disclosure, promise-vs-delivery) mapped 1–5 → 0–100; needs a dossier ≤ 90 days old with ≥ 3 verified grades |

Three pre-registered variants only (`base`, `quality_tilt`, `value_tilt`). Composite `S = Σ wᵢPᵢ / Σ wᵢ` over known pillars (absent pillars renormalised away, never zero-filled).

**Notch**: STRONG_BUY ≥ 80, BUY ≥ 65, HOLD ≥ 40, REDUCE ≥ 25, else SELL; `verdict` BUY / HOLD / SELL. **Gates cap the notch, never the score** (all listed in `gates_json`): GSM → REDUCE; ASM stage ≥ 2 → HOLD; F&O ban → HOLD; pledge > 50% → REDUCE; Altman Z'' < 1.1 (non-financial) → REDUCE; qualified/adverse/disclaimer opinion or auditor resignation ≤ 12m → REDUCE; rating D or default event ≤ 90d → SELL; Beneish flag in both of the last two FYs → HOLD; statements > 200 days old → HOLD. **DATA_ERROR → `NO_RATING`** (with named causes, xirr-engine style) when weight coverage < 0.60, Quality or Valuation UNKNOWN, price history < 120 sessions, statements > 400 days old, metrics slice missing, or confidence < 0.35.

**Confidence** = (0.5 × pillar coverage + 0.5 × component coverage) × 0.85^flags × staleness (1.0 ≤ 120d / 0.85 ≤ 200d / 0.70) × agreement (0.9 when |Qualitative − S| > 30); flags = XBRL-vs-screener mismatch > 10%, implausible P/E, PAT CAGR discontinuity > 150%, history < 240 sessions. Bands HIGH ≥ 0.75, MED ≥ 0.50, LOW. **Expected-return band** (informational): `er_mid = earnings_yield + clip(median(sales, pat CAGR 3y), −10%, 20%) + clip(ln(pe_median_10y / pe_ttm)/3, ±15%)`, `± max(10%, vol_250/√3)`. **Manifest** lists every input with value, status, provenance and a sha256 of inputs + weights + thresholds + engine version (identical inputs → identical hash, tested).

**Calibration** (`calibrate.py`, bar pre-registered in `acceptance.py` before the first run): month-end signal dates 2017-06-30 (r1) / 2019-06-30 (r2+) → end − 12m; names = PIT liquidity universe; forward 12m adjusted return, delisted exit at last close × 0.99, benchmark NIFTY 500 + 1.3%/yr TR proxy; expanding yearly folds 2019–2024 with a 12-month embargo, variant chosen per fold on train IC, holdout 2024-09 → 2025-08 evaluated once; deflated Sharpe with 3 trials. Bar (all must hold): buckets strictly monotonic overall and in ≥ 70% of test years; long-short (BUY tier − SELL tier) ≥ 6 pp/yr with Newey–West t ≥ 2; mean IC ≥ 0.05 with t ≥ 2; BUY-tier hit rate ≥ 55% and SELL-tier hit rate ≥ 55%; OOS Brier ≤ 0.24 and ≥ 0.01 better than climatology (isotonic map fitted on train folds only); DSR p < 0.05; monthly notch transition ≤ 25%; no notch below 5% of the universe on average; holdout long-short positive. Verdict `VALIDATED` / `NOT VALIDATED` per engine version travels with every rating (page pill, advisor `validated` flag, digest "diagnostic" label). `rating_ledger` is append-only; every nightly publish is scored at 12 months; prospective hit rates are quoted only with ≥ 100 matured rows and ≥ 20 per tier. Any weight/threshold/gate change bumps `ENGINE_VERSION` and requires a new calibration.

### 3.6 Fundamental knowledge graph (Phase 5) — `eqr/graph/`

Store = DuckDB `graph_nodes` + bi-temporal `graph_edges` (identity `(src, type, dst, evidence)`, `derived_by` lanes so a rebuild clears only its own lane, `valid_to` closes edges, `visible_from` for PIT loads) + `graph_aliases`; algorithms = NetworkX `MultiDiGraph` loaded as of a date. Deterministic builders: industry/sector/index, promoters and named holders (SHP XBRL; `HOLDER_DENYLIST` for trusts/LIC-style entities), auditors (XBRL `AuditorsFirmName`, annual-report signature block), rating agencies (credit_ratings), subsidiaries (AOC-1 extractor). LLM-extracted edges (customers, suppliers, JVs, lenders, litigation, directors from the dossier's related-entities section) are stored with citation and confidence, displayed and exported, but **do not score** until coverage ≥ 50% of the universe and a calibration shows IC; Cohen–Frazzini economic-link momentum is a later pre-registered experiment. `graph_features` (PIT): promoter-group id/size, group pledge max, group surveillance, group downgrades 12m, auditor and client count, auditor qualified share 24m, auditor_small, sector downgrade share 12m. Outputs: `eqr graph build|features|export --fmt graphml|json`, symbol-page neighbourhood inline SVG, `/graph` page (risk clusters, node search), full-universe GraphML.

### 3.7 Research workflow (Phase 6) — `eqr research SYMBOL [--deep] [--batch]`

- **LLM adapter** `research/llm.py`: `LLM` protocol with `AnthropicLLM` (official SDK, model `claude-opus-5`, adaptive thinking by omission, structured outputs via `output_config.format`, frozen system prompt + schema under prompt caching, `fallbacks: "default"` with the `server-side-fallback-2026-07-01` beta, Batches submit/collect, token and USD accounting, guards `EQR_LLM_PER_RUN_USD` and `EQR_LLM_MONTHLY_USD`), `CliLLM` (`claude -p` fallback, no web), `FakeLLM` for tests. The implementer reads the `claude-api` skill's Python README before writing this file.
- **Quick pass** (one structured call): pack v2 (metrics with percentiles, provisional rating + manifest, graph neighbourhood, filings, news, prioritised `doc_sections` under a 110k-token budget) → dossier v2: thesis, bull/bear, grades (six qualitative areas), sector KPIs, related entities, red flags, catalysts, `llm_view` (stored, never published as the rating), disagreements with the engine. Every document claim carries a verbatim `quote`; every table claim a `table_ref`.
- **Deterministic verifier** `research/verify.py`: quote matched (exact, then normalised fuzzy) against `doc_sections.text`; table refs checked against the pack within 1%; web claims must cite URLs harvested from the tool-result blocks. Struck claims move to `data_gaps`; > 25% struck → run REJECTED, nothing stored; results land in `dossier_claims`.
- **Deep mode** adds: a web pass (`web_search_20260209` max_uses 8 + `web_fetch_20260209` max_uses 6, `EQR_WEB_ALLOWED_DOMAINS`) whose findings and sources go to `web_sources`; and a fresh-context LLM verifier (`claude-sonnet-5`, claim + evidence only, strike-only). Then the engine re-runs with the Qualitative pillar (r3) and the dossier stores both `engine_rating` and `llm_view`.
- Fan-in guard: the run aborts with `DATA_ERROR` if the pack lacks the rating, metrics or sections it expected. `research_runs` records passes, tokens and cost.

Cost at list prices (Opus 5 $5/$25 per MTok, Sonnet 5 $2/$10): quick ≈ $0.55 sync / $0.28 in Batches; deep ≈ $1.20 (+ web pass ≈ $0.30, verifier ≈ $0.06). Weekly batch of ~60 names (held + top 40) plus ~20 deep runs ≈ $30/week ≈ $130/month; cap $150 (`EQR_LLM_MONTHLY_USD`). Nightly rating: $0.

### 3.8 Surfaces and schedule (Phase 7)

`/symbol/{s}` Research section (rating card with notch/verdict/score/confidence/ER band/gates/validated pill, pillar bars, forensic decile table, valuation bands, governance timeline, graph neighbourhood SVG, news, dossier v2 with quotes linked to `/doc/{doc_id}#p<n>`); `/ratings` (sortable, filters, CSV); `/graph`; `/doc/{doc_id}`; advisor `rating` block (`as_of, rating, verdict, score, confidence, gated, validated`) with `advisor_client.evidence_line` able only to zero points on a validated SELL, never to gate; digest lines for rating changes, new gates and completed research on held names. `deploy/mac/jobs.py` chains per §3.1; new `com.eqr.research` plist (Sunday 03:00); systemd twins without a research unit (Claude runs only on the Mac).

## 4. Phases and tasks

Conventions: pytest per task with synthetic fixtures (`tests/conftest.py::make_synthetic_market` extended with XBRL, filings, holders and a `planted_quality` signal), no network in tests, one commit per task, idempotent loaders. Version bumps to `eqr 0.2.0` at the end.

**T0.0 Docs.** documentation-engineer materialises the approved design as `docs/superpowers/specs/2026-09-14-fundamentals-x10-design.md` and the TDD plan as `docs/superpowers/plans/2026-09-14-fundamentals-x10-plan.md` from this file; `DOCS_INDEX.md` entry.

### Phase 0 — Spikes (1 day; notes to `data/spikes/`, gitignored)

| # | Spike | Command / check | Go / no-go |
|---|---|---|---|
| S0.1 | XBRL taxonomy map + cookie gating | `curl` (no cookies) the 2018, 2024, 2026 and one bank XML; lxml print nsmap, localnames, contexts, units, `*Rounding*` tags | GO when a tag→canonical map covers the ~45 items in all namespaces and the rounding vocabulary is known; NO-GO → raw tags + scale inferred from screener |
| S0.2 | SHP pledge tags | SHP XML for SUZLON, JPPOWER, VEDL; grep `Pledg|Encumb|NameOfTheShareholder|NumberOfShares` | GO when a per-holder pledged-count tag and its context→holder mapping exist; NO-GO → promoter-level boolean pledge |
| S0.3 | Insider date window | DevTools on the NSE insider page → replay the request | GO adds a backfill task; NO-GO (expected) keeps the forward-only ledger |
| S0.4 | Credit-rating history start | bisect monthly windows Apr–Aug 2023 | first non-empty month = backfill start |
| S0.5 | Dependencies | `uv pip install --dry-run anthropic lxml networkx feedparser pdfplumber` (+ `docling`) | pin in pyproject; drop the docling extra if unresolvable |
| S0.6 | Claude smoke (needs `ANTHROPIC_API_KEY`) | structured output call; structured + web tools call; 2-request batch; `count_tokens` on the RELIANCE pack + 3 sections | GO on 200s and 25–90k tokens; NO-GO on tools+format → web pass becomes a separate unstructured call |
| S0.7 | Section locator + tables | regexes over the two stored RELIANCE ARs and three transcripts; pdfplumber on the contingent-liabilities page | GO when ≥ 8/10 kinds found on both ARs and ≥ 1 numeric table row extracted; NO-GO → pymupdf, then docling |
| S0.8 | docling timing (optional) | one AR on CPU | keep the extra only if < 1 s/page and visibly better tables |

### Phase 1 — Spine (3–4 days)

| # | Task | Files | Interfaces / tests | Done when |
|---|---|---|---|---|
| T1.1 | Schema + migrations | `eqr/store/schema.sql`, new `migrations.sql`, `db.py` | `init_schema` runs schema then migrations; `test_schema_v2_tables_and_migrations_are_idempotent`, `test_new_tables_carry_as_of_and_visible_from` | fresh file creates all tables; re-run is a no-op |
| T1.2 | XBRL URLs in results_calendar | `spine/nse_api.py`, `cli.py` (`reference --xbrl-urls-from`) | `fetch_financial_results`/`fetch_integrated_results` return `xbrl_url, seq_id, type_sub` (placeholder `/-` → NULL); `fill_xbrl_urls(con, api, run_id, start, end)` fills NULLs only, `filing_dt` untouched | fixture feed test; first-seen filing date preserved |
| T1.3 | XBRL parser + PIT loader | new `spine/xbrl.py`, fixtures `xbrl_q_2018.xml`, `xbrl_fy_2024.xml`, `xbrl_q_2026_capmkt.xml`, `xbrl_bank_2026.xml` | `parse_xbrl(bytes) -> ParsedXbrl`; `period_kind(start, end)`; `canonical_item(tag, is_bank)`; `load_parsed_xbrl(con, symbol, parsed, filing_dt, source_url)`; `infer_scale(con, symbol, parsed)`; `canonical_wide(con, symbol, as_of)`; tests for each taxonomy, lakh→crore scaling, auditor read, bank-only items, first-seen + revisions, dimensioned segment facts | all fixtures parse to canonical items |
| T1.4 | `eqr xbrl` sweep + quality | `cli.py`, `spine/xbrl.py`, `spine/quality.py` | `sweep_xbrl(con, http, rows, run_id, stop_after_blocked=5)` with immutable raw archive; flags `--backfill-from --recent --symbols --limit --rate`; checks `xbrl_screener_agreement` (≥ 90% of FY pairs within 5%), `xbrl_freshness` | sweep resumes from archive at zero cost; backfill 2018→ started in the background |
| T1.5 | NSE filings | new `spine/nse_filings.py`, fixtures `credit_rating_sample.json`, `board_meetings_sample.json`, `pit_sample.json`, `shp_sample.xml`, `shp_index_sample.json` | `normalise_rating(text) -> (rating, notch, term)`; `fetch_credit_ratings(api, start, end)`; `match_company(con, name, isin)`; `fetch_board_meetings`; `fetch_insider_trades(api, symbol)`; `fetch_shp_index`; `parse_shp_xbrl(content)`; `load_shp(...)`; `load_filings_daily(con, api, run_id, as_of, lookback_days=7)`; `load_symbol_filings2(con, api, run_id, symbol, shp_quarters=8)`; tests: rating strings, ISIN-then-name matching with no false match, SHP holders + pledge %, insider first-seen, meeting purpose kinds | fixtures load with correct `visible_from`; live `eqr filings2 --symbols RELIANCE` |
| T1.6 | CLI, PIT readers, jobs | `cli.py` (`filings2 --daily|--symbols|--universe-insider|--ratings-backfill-from`), `store/pit.py`, `deploy/mac/jobs.py`, `deploy/systemd/eqr-refresh.service`, `tests/test_launchd.py` | `xbrl_as_of`, `holders_as_of`, `pledges_as_of`, `ratings_as_of`, `insider_as_of` (filter `visible_from <= as_of`); `test_pit_readers_hide_future_visible_from`, `test_refresh_chain_includes_filings2_and_xbrl` | nightly chain runs end-to-end on the Mac |

### Phase 2 — Fundamentals (3 days)

| # | Task | Files | Interfaces / tests | Done when |
|---|---|---|---|---|
| T2.1 | Framework | new `fundamentals/base.py` | `Metric`, `MetricSet.v/rows`, `Inputs` dataclass, `load_inputs(con, as_of, symbols)`, `percentile_grouped(s, groups, min_group=8)`, `is_financial(industry, a)`; tests: UNKNOWN has no value, grouped percentile fallback, inputs respect visibility | — |
| T2.2 | Forensic | new `fundamentals/forensic.py` | `compute(inp) -> MetricSet` (list in §3.4), `beneish(x0, x1) -> MScore|None`, `sloan(pat, cfo, ta)`; tests: Beneish equals the hand-computed example to 1e-6, abstains below 6 components, reserves leakage 0 when reserves track retained profit, financials get NA not zero, UNKNOWN never zero-fills | — |
| T2.3 | Quality | new `fundamentals/quality.py` | `compute(inp)`; tests on the synthetic market; NA for financials | — |
| T2.4 | Valuation | new `fundamentals/valuation.py` | `wacc(beta, rf_pct, erp_pct, debt_weight, kd_pct, tax=0.25)`, `implied_growth(mcap_cr, fcf0_cr, wacc, years=10, g_terminal=0.05)`, `own_band_position(series, current)`, `justified_pb(roe, coe, g)`, `expected_return_band(ey, g_sust, pe_now, pe_median, vol)`; tests: implied growth recovers a planted g, band median = 0.5, ER monotone in EY | — |
| T2.5 | Governance | new `fundamentals/governance.py` | `compute(inp)`, `adverse_events(ann, as_of, days=90)`; tests: pledge/insider from fixtures, auditor change across FYs, rating migration notches, adverse keywords | — |
| T2.6 | Sector KPIs | new `fundamentals/sector_kpis.py` | bank/NBFC KPIs from the XBRL fixture; non-financials return an empty set | — |
| T2.7 | Metrics build + CLI | new `fundamentals/build.py`, `cli.py` (`metrics --as-of|--monthly-from|--symbols`) | `METRICS_VERSION = "m1"`; `build_metrics(con, as_of, symbols=None, store=True)` replaces the `(as_of, engine_version)` slice; tests: end-to-end rows and statuses, PIT | `eqr metrics --monthly-from 2017-06-30` runs (≈ 3–5 h once) |

### Phase 3 — Rating and calibration (3 days; starts as soon as Phase 2 lands, before the XBRL backfill finishes)

| # | Task | Files | Interfaces / tests | Done when |
|---|---|---|---|---|
| T3.1 | Pillars + engine (pure) | new `rating/pillars.py`, `rating/engine.py`, `tests/test_rating_engine.py`, `tests/test_layering.py` | `ENGINE_VERSION`, `WEIGHTS[variant]`, `QUAL_MAX_WEIGHT`, `THRESHOLDS`, `ORDER`; `Component`, `Gate`, `PillarScore`, `RatingResult.to_row()`; `pillar_score(name, pct, raw, status, is_financial, variant)`; `evaluate_gates(raw, flags)`; `rate_symbol(symbol, as_of, pct, raw, status, flags, variant="base")`; `rate_universe(con, as_of, variant, store=True)`; tests: best-in-class → STRONG_BUY, gates cap notch not score, UNKNOWN lowers confidence not score, low coverage → NO_RATING with named errors, manifest sha deterministic, QUAL weight capped, no upward imports | 25+ table-driven cases pass |
| T3.2 | Storage, ledger, CLI | new `rating/ledger.py`, `cli.py` (`rate --universe|--symbol [--as-of] [--variant] [--publish]`) | `store_ratings`, `publish(con, as_of, engine_version)` append-only, `mature(con, today)`, `latest_rating(con, symbol)`; tests: publish idempotent, maturity uses adjusted closes + delisting haircut, ledger rows never rewritten | `eqr rate --universe --publish` writes ratings + ledger |
| T3.3 | Calibration | new `rating/calibrate.py`, `acceptance.py`, `report.py`, `cli.py` (`rate --calibrate --engine r1 --start --holdout-start`), `conftest.py` (`planted_quality`) | `CalibrationConfig(engine_version, start, end, holdout_start, fold_years, horizon_days=365, variants=("base","quality_tilt","value_tilt"))`; `forward_returns`, `rating_history`, `bucket_stats`, `ic_series`, `long_short`, `nw_tstat(x, lag=11)`, `brier(train, test)`, `run_calibration`, `evaluate(...)`, `write_calibration_report`; tests: planted signal → monotone buckets + IC, random market fails the bar, Newey–West hand value, isotonic Brier beats climatology | real r1 calibration run and report stored |
| T3.4 | Engine r2 | `pillars.py`, `engine.py` | `ENGINE_VERSION = "r2"`, Forensic pillar enabled; calibration re-run from 2019-06-30 | after the XBRL backfill |

### Phase 4 — Documents (2 days)

| # | Task | Files | Interfaces / tests | Done when |
|---|---|---|---|---|
| T4.1 | Docstore hardening | `research/docstore.py`, new `tests/test_docstore.py` | `extract_text(pdf_path, max_pages=400) -> (text, pages, status)`; `sync_symbol_documents(..., max_docs=24)` with per-kind caps; non-PDF bytes recorded, not stored | — |
| T4.2 | Section locator + doc_sections | new `research/docparse.py`, fixtures `ar_pages_sample.txt`, `transcript_pages_sample.txt` | `SECTION_PATTERNS`, `MAX_PAGES`, `Section`, `split_pages`, `locate_sections(pages, doc_kind)`, `extract_tables(pdf_path, pages, extractor=None)`, `parse_document(con, doc_id, force=False)`, `parse_pending(con, symbols=None, recent_days=None)`; tests: eight kinds located with page ranges, transcript split into prepared/Q&A, idempotent + force, tables via injected extractor | — |
| T4.3 | Note extractors | `docparse.py`, `fundamentals/base.py` (`Inputs.docs`) | `contingent_liabilities_total`, `auditor_remuneration_total`, `rpt_totals`, `subsidiaries_list`, `doc_metrics(con, symbol, as_of)`; tests incl. scale headers and absence → None | governance/forensic doc metrics flow into `fund_metrics` |
| T4.4 | CLI + jobs | `cli.py` (`docs fetch`, `docs parse [--symbols|--recent|--all] [--force]`), `deploy/mac/jobs.py` | weekly chain parses recent docs | — |

### Phase 5 — Graph (2–3 days)

| # | Task | Files | Interfaces / tests | Done when |
|---|---|---|---|---|
| T5.1 | Model + store | new `graph/model.py`, `graph/store.py` | `node_id(kind, name)`, `Node`, `Edge`, `upsert_nodes`, `upsert_edges`, `clear_edges(con, evidence_prefix, derived_by)`, `close_edges(con, src, type, valid_to, derived_by)`, `load_graph(con, as_of=None, kinds=None) -> nx.MultiDiGraph`; tests: identity dedups, lane-scoped clear, PIT + valid_to respected | — |
| T5.2 | Deterministic builders | new `graph/builders.py` | `industry_edges`, `promoter_edges(con, quarters=8)`, `auditor_edges`, `rating_edges`, `subsidiary_edges`, `build_deterministic(con, as_of=None)`, `HOLDER_DENYLIST`; tests: valid_to on holder dropout, denylist, auditor + rating edges | — |
| T5.3 | Graph features | new `graph/features.py` | `group_components(G)`, `graph_features(con, as_of, store=True)`; tests: group pledge propagates, singleton group, PIT | — |
| T5.4 | Export, layout, CLI | new `graph/export.py`, `graph/layout.py`, `cli.py` (`graph build|features|export --fmt graphml|json --out`) | `export_graph(con, path, fmt)`, `neighbourhood_svg(G, symbol, radius=1)`, `group_svg(G, group_id)`; tests: export round-trip counts, one circle per node | GraphML loads in NetworkX |

### Phase 6 — Research (4 days)

| # | Task | Files | Interfaces / tests | Done when |
|---|---|---|---|---|
| T6.1 | LLM adapter | new `research/llm.py`, `config.py` (+ `EQR_ERP_PCT`, `EQR_LLM_MONTHLY_USD`, `EQR_LLM_PER_RUN_USD`, `EQR_CLAUDE_VERIFIER_MODEL`, `EQR_WEB_ALLOWED_DOMAINS`, `EQR_RESEARCH_TOP_N`, `EQR_DOC_PARSER`), `.env.example` | `Usage(...).cost_usd(batch=False)`; `LLM.structured(*, system, blocks, schema, model, max_tokens=16000, tools=None, cache_prefix=True) -> (obj, usage, blocks)`; `AnthropicLLM.submit_batch/collect_batch`; `CliLLM`; `FakeLLM`; `default_llm()`; `BudgetExceeded`; tests with the fake transport | S0.6 shapes reproduced |
| T6.2 | Schema v2 + verifier | `research/schema.json`, `schema.py`, new `research/verify.py`, fixture `dossier_v2_good.json` | `validate_dossier(obj, allowed_docs, allowed_sections=frozenset(), allowed_web=frozenset())`; `quote_supported(quote, text) -> (ok, score)`; `table_supported(ref, pack, tol=0.01)`; `verify_claims(obj, sections, pack, web_ids)`; `REJECT_STRUCK_SHARE = 0.25`; tests: exact and fuzzy quotes, paraphrase fails, table tolerance, strike under threshold keeps, reject over, v1 dossier still valid | — |
| T6.3 | Pack v2 | `research/pack.py` | `build_pack(con, symbol, as_of=None, max_tokens=110_000, deep=False)` adds metrics, rating, graph, filings, news, sections; `TABLE_CITATIONS` extended; token budget test | — |
| T6.4 | News | new `research/news.py`, `cli.py` (`news SYMBOLS`), fixture `news_rss_sample.xml` | `fetch_news(http, query)`, `parse_rss(text)`, `load_news(con, symbol, items)`; fail-soft | — |
| T6.5 | Orchestrator | new `research/research.py`, `dossier.py` (v2 markdown), `cli.py` (`research SYMBOL [--deep] [--as-of] [--dry-run] [--no-refresh]`) | `run_research(con, symbol, as_of=None, mode="quick", llm=None, refresh=True, dry_run=False, model=None) -> {status, run_id, verified, struck, cost_usd, path}`; `qualitative_pillar_input(con, symbol, as_of, max_age_days=90)`; frozen `SYSTEM_V2`; tests: quick run stores dossier, claims and LLM edges; unverifiable quotes reject and store nothing; `--no-refresh` never touches the network; DATA_ERROR when the pack lacks the rating | — |
| T6.6 | Deep web pass | `research.py`, `llm.py` | `web_pass(con, symbol, run_id, pack, llm, model) -> (findings, web_sources rows)`; `harvest_web_sources(blocks)`; `WEB_TOOLS(allowed_domains)`; tests: harvest from tool-result blocks, web claim must cite a harvested URL, `pause_turn` restarts bounded | — |
| T6.7 | Batches | `research.py`, `cli.py` (`research --batch [--held] [--top N]`, `research-collect BATCH_ID|--latest [--wait MIN]`) | `submit_research_batch(con, symbols, as_of, llm, model) -> batch_id`; `collect_research_batch(con, batch_id, llm)`; per-symbol accounting tests | live run for 3 symbols (bank, manufacturer, small cap) with cost recorded |

### Phase 7 — Surfaces and schedule (2–3 days)

| # | Task | Files | Done when |
|---|---|---|---|
| T7.1 | Symbol Research section + `/doc/{doc_id}` | `surfaces/queries.py`, `surfaces/svg.py`, templates `symbol.html`, `doc.html`, `tests/test_surfaces_research.py` | every block renders from fixture data; quotes link to the section page |
| T7.2 | `/ratings` and `/graph` pages, CSV export | `surfaces/web/app.py`, templates | 200s with content; CSV columns match `ratings` |
| T7.3 | Advisor `rating` block | `surfaces/queries.py`, `surfaces/advisor_client.py`, `tests/test_advisor_client.py` | validated SELL zeroes points (status FAIL), never gates; unvalidated → unchanged; block may be None |
| T7.4 | Digest additions | `surfaces/digest.py` | rating changes, new gates and completed research for held names |
| T7.5 | Scheduling | `deploy/mac/jobs.py`, `deploy/mac/launchd/com.eqr.research.plist`, `install-mac.sh` LABELS, `deploy/systemd/*`, `tests/test_launchd.py` | chains per §3.1; `plutil -lint` clean; no research unit on the VM |
| T7.6 | Version bump + handoff | `pyproject.toml` 0.2.0, health `version`, `.env.example` | documentation-engineer updates `DATA_SOURCES.md`, `OPERATIONS.md`, `VALIDATION.md` (rating calibration section), `REBUILD_SPEC.md`; production-engineer pushes, updates the registry and re-installs the launchd agents |

## 5. Verification (end to end)

1. `.venv/bin/pytest -q`: the existing 45 tests plus the new suites pass; `test_layering.py` and `test_no_network` guards hold.
2. Spike notes in `data/spikes/` show the taxonomy map, SHP pledge tags, credit-rating history start, dependency resolution and the Claude smoke shapes.
3. Real data: `eqr xbrl --recent` then `--backfill-from 2018-03-31` (background); `eqr filings2 --daily`; `eqr metrics`; `eqr rate --universe --publish` → `/ratings` populated with score, confidence, gates, validated pill.
4. `eqr rate --calibrate --engine r1` → report with the acceptance table; verdict shown on `/ratings`, in the advisor JSON and the digest. Repeat for r2 after the backfill.
5. `eqr docs parse --symbols RELIANCE` → sections with page ranges; `eqr graph build && eqr graph features` → neighbourhood SVG on `/symbol/RELIANCE`; `eqr graph export --fmt graphml` loads in NetworkX.
6. `eqr research RELIANCE` (quick) and `--deep`: dossier v2 stored with `dossier_claims`, struck claims listed, `research_runs` shows tokens and USD within the estimate; an intentionally unsupported quote in a fixture run is rejected.
7. Browser: `/symbol/RELIANCE`, `/ratings`, `/graph`, `/doc/<id>` in the light theme without console errors; `curl -H "Authorization: Bearer $EQR_ADVISOR_TOKEN" 127.0.0.1:8801/advisor/v1/evidence/RELIANCE` shows the `rating` block.
8. `python deploy/mac/jobs.py refresh|fundamentals|research` dry-runs from a terminal before production-engineer installs the agents.

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| NSE 403 storms / endpoint changes | existing throttle, proxy and raw-archive pattern; small daily windows; every loader degrades to a quality flag; nsearchives XBRL/SHP fetched with the archive client (cookie need confirmed in S0.1) |
| XBRL backfill size and throttling (≈ 107k files) | 1 req/s over nights, resumable archive, priority symbols first; engine r1 does not wait for it |
| Silent 100× scaling errors | rounding tag + `infer_scale` cross-check vs screener; agreement quality check; mismatches lower confidence |
| Taxonomy drift | raw tags stored; canonical map is data; `xbrl_unmapped_core_tags` check |
| Pledge count tag missing in SHP | promoter-level boolean until mapped (S0.2) |
| Credit-rating name matching | ISIN first, normalised name second, `graph_aliases` for manual fixes, matched share reported |
| LLM hallucination | verbatim-quote and table-ref verification, strike-only LLM verifier, engine owns the rating, Qualitative weight 0.05 (≤ 0.20 asserted), LLM edges never score until calibrated |
| LLM cost | per-run and monthly USD guards, Batches, caching, Sonnet verifier, costs in `research_runs` and the digest |
| Overfitting the rating | pre-registered bar, 3 variants only, embargoed folds, one-shot holdout, DSR, versioned engine, prospective ledger as the final arbiter |
| Survivorship before 2018 | XBRL covers the 333 absent filing symbols from FY2018; r2 calibration reported from 2019; caveat travels with the verdict |
| DuckDB single writer | jobs serialised in `jobs.py`, archive-then-load steps, web read-only |
| PIT leakage via `fetched_at` | every new table's `visible_from` comes from broadcast/filing dates; PIT readers filter on it; tests assert hidden rows |
| Disk (≈ 5 GB XBRL + ≈ 9 GB SHP) | SHP limited to 8 quarters; 232 GB free today |

## 7. Effort and cost

≈ 20–24 agent-days across Phases 0–7 (spikes 1; spine 3–4; fundamentals 3; rating 3; documents 2; graph 2–3; research 4; surfaces 2–3). Machine time: XBRL backfill ≈ 2 nights, monthly metrics backfill ≈ 3–5 h once, calibration ≈ 30–60 min per engine version, nightly rating < 5 min. Money: ≈ $130/month steady state for the weekly research batches, capped at $150; everything else $0.

## 8. Also recommended, outside this plan

Sleeve S redesign with a pre-registered 8–12 week hold; a validated "Sleeve F" that trades the rating (only after r2 is VALIDATED, through the existing walk-forward); provisioning the non-OCI VM; Telegram token; the parked Mac launchd deploy grant.

---

## Appendix A — DDL for every new table (append to `eqr/store/schema.sql`; ALTERs go in `eqr/store/migrations.sql`)

```sql
-- Phase 1: XBRL statements (Ind-AS results filings). Values in INR crore after scaling; first-seen wins.
CREATE TABLE IF NOT EXISTS statements_xbrl (
  symbol VARCHAR, basis VARCHAR, period_end DATE, period_start DATE, kind VARCHAR,       -- kind: D (duration) | I (instant)
  period_kind VARCHAR, tag VARCHAR, item VARCHAR, dims_key VARCHAR, value DOUBLE, text_value VARCHAR,
  unit VARCHAR, taxonomy VARCHAR, filing_dt TIMESTAMP, fetched_at TIMESTAMP, as_of DATE, visible_from DATE,
  PRIMARY KEY (symbol, basis, period_end, kind, tag, dims_key));
CREATE TABLE IF NOT EXISTS statements_xbrl_revisions (
  symbol VARCHAR, basis VARCHAR, period_end DATE, kind VARCHAR, tag VARCHAR, dims_key VARCHAR,
  value DOUBLE, text_value VARCHAR, filing_dt TIMESTAMP, fetched_at TIMESTAMP, source_url VARCHAR,
  PRIMARY KEY (symbol, basis, period_end, kind, tag, dims_key, fetched_at));
CREATE TABLE IF NOT EXISTS xbrl_filings (
  symbol VARCHAR, period_end DATE, basis VARCHAR, xbrl_url VARCHAR, filing_dt TIMESTAMP, taxonomy VARCHAR,
  status VARCHAR, facts INTEGER, rounding VARCHAR, scale_to_cr DOUBLE, scale_inferred BOOLEAN, is_bank BOOLEAN,
  revised BOOLEAN, seq_id VARCHAR, sha256 VARCHAR, bytes BIGINT, fetched_at TIMESTAMP, error VARCHAR,
  PRIMARY KEY (symbol, period_end, basis, xbrl_url));

-- Phase 1: filings
CREATE TABLE IF NOT EXISTS credit_ratings (
  app_id VARCHAR, symbol VARCHAR, company_name VARCHAR, isin VARCHAR, agency VARCHAR,
  rating_raw VARCHAR, rating VARCHAR, notch INTEGER, term VARCHAR, outlook VARCHAR, action VARCHAR,
  prev_rating VARCHAR, prev_notch INTEGER, prev_outlook VARCHAR, prev_dt DATE, rating_dt DATE,
  broadcast_dt TIMESTAMP, xbrl_url VARCHAR, fetched_at TIMESTAMP, as_of DATE, visible_from DATE,
  PRIMARY KEY (app_id));
CREATE TABLE IF NOT EXISTS board_meetings (
  symbol VARCHAR, meeting_dt DATE, purpose VARCHAR, description VARCHAR, kind VARCHAR,          -- kind: results | dividend | fund_raise | other
  intimation_dt TIMESTAMP, attachment_url VARCHAR, fetched_at TIMESTAMP, as_of DATE, visible_from DATE,
  PRIMARY KEY (symbol, meeting_dt, purpose));
CREATE TABLE IF NOT EXISTS insider_trades (
  symbol VARCHAR, disclosure_id VARCHAR, person VARCHAR, category VARCHAR, security_type VARCHAR, mode VARCHAR,
  side VARCHAR, qty BIGINT, value_inr DOUBLE, pre_pct DOUBLE, post_pct DOUBLE, from_dt DATE, to_dt DATE,
  intimation_dt DATE, broadcast_dt TIMESTAMP, regulation VARCHAR, xbrl_url VARCHAR, fetched_at TIMESTAMP,
  as_of DATE, visible_from DATE, PRIMARY KEY (symbol, disclosure_id));
CREATE TABLE IF NOT EXISTS holders_named (
  symbol VARCHAR, period_end DATE, category VARCHAR, holder VARCHAR, holder_kind VARCHAR,       -- person | entity | trust | government | institution
  shares BIGINT, pct DOUBLE, pledged_shares BIGINT, pledged_pct DOUBLE, locked_shares BIGINT,
  source_url VARCHAR, fetched_at TIMESTAMP, as_of DATE, visible_from DATE,
  PRIMARY KEY (symbol, period_end, category, holder));
CREATE TABLE IF NOT EXISTS pledges (
  symbol VARCHAR, period_end DATE, source VARCHAR, promoter_shares BIGINT, promoter_pledged_shares BIGINT,
  pledged_pct_of_promoter DOUBLE, pledged_pct_of_total DOUBLE, encumbered_other_flag BOOLEAN,
  fetched_at TIMESTAMP, as_of DATE, visible_from DATE, PRIMARY KEY (symbol, period_end, source));

-- Phase 4: documents
CREATE TABLE IF NOT EXISTS doc_sections (
  doc_id VARCHAR, section_kind VARCHAR, seq INTEGER, page_start INTEGER, page_end INTEGER, heading VARCHAR,
  text VARCHAR, tables_json VARCHAR, chars INTEGER, method VARCHAR, confidence DOUBLE, parser_version VARCHAR,
  created_at TIMESTAMP, PRIMARY KEY (doc_id, section_kind, seq));

-- Phase 2: metrics (long format, one row per metric, PIT as-of)
CREATE TABLE IF NOT EXISTS fund_metrics (
  as_of DATE, symbol VARCHAR, metric VARCHAR, value DOUBLE, status VARCHAR, unit VARCHAR,
  source_table VARCHAR, source_keys VARCHAR, inputs_as_of DATE, note VARCHAR, engine_version VARCHAR,
  PRIMARY KEY (as_of, symbol, metric));

-- Phase 5: graph (edge identity = src,type,dst,evidence; lanes = derived_by)
CREATE TABLE IF NOT EXISTS graph_nodes (
  id VARCHAR PRIMARY KEY, kind VARCHAR, name VARCHAR, attrs_json VARCHAR, as_of DATE,
  derived_by VARCHAR, first_seen_at TIMESTAMP, updated_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS graph_edges (
  src VARCHAR, type VARCHAR, dst VARCHAR, evidence VARCHAR, valid_from DATE, valid_to DATE,
  confidence DOUBLE, derived_by VARCHAR, attrs_json VARCHAR, as_of DATE, visible_from DATE, created_at TIMESTAMP,
  PRIMARY KEY (src, type, dst, evidence));
CREATE TABLE IF NOT EXISTS graph_aliases (alias VARCHAR PRIMARY KEY, node_id VARCHAR, note VARCHAR, added_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS graph_features (
  as_of DATE, symbol VARCHAR, group_id VARCHAR, group_size INTEGER, group_pledge_max DOUBLE,
  group_surveillance INTEGER, group_downgrades_12m INTEGER, auditor VARCHAR, auditor_clients INTEGER,
  auditor_qualified_share_24m DOUBLE, auditor_small INTEGER, sector_downgrade_share_12m DOUBLE,
  status VARCHAR, PRIMARY KEY (as_of, symbol));

-- Phase 3: rating
CREATE TABLE IF NOT EXISTS ratings (
  symbol VARCHAR, as_of DATE, engine_version VARCHAR, variant VARCHAR, status VARCHAR, rating VARCHAR,
  score DOUBLE, confidence DOUBLE, confidence_band VARCHAR, er_lo DOUBLE, er_mid DOUBLE, er_hi DOUBLE,
  coverage DOUBLE, pillars_json VARCHAR, gates_json VARCHAR, manifest_json VARCHAR, manifest_sha VARCHAR,
  data_errors_json VARCHAR, created_at TIMESTAMP, PRIMARY KEY (symbol, as_of, engine_version, variant));
CREATE TABLE IF NOT EXISTS rating_ledger (
  symbol VARCHAR, as_of DATE, engine_version VARCHAR, published_at TIMESTAMP, rating VARCHAR, score DOUBLE,
  confidence DOUBLE, close_at_publish DOUBLE, horizon_days INTEGER, matured_at DATE, fwd_return DOUBLE,
  bench_return DOUBLE, excess_return DOUBLE, outcome VARCHAR,                                  -- outcome: pending | hit | miss | delisted
  PRIMARY KEY (symbol, as_of, engine_version));
CREATE TABLE IF NOT EXISTS rating_calibrations (
  run_id VARCHAR PRIMARY KEY, engine_version VARCHAR, start_date DATE, end_date DATE, holdout_start DATE,
  n_obs INTEGER, metrics_json VARCHAR, acceptance_json VARCHAR, verdict VARCHAR, report_path VARCHAR, created_at TIMESTAMP);

-- Phase 6: research
CREATE TABLE IF NOT EXISTS research_runs (
  run_id VARCHAR PRIMARY KEY, symbol VARCHAR, as_of DATE, mode VARCHAR, model VARCHAR, status VARCHAR,
  passes_json VARCHAR, input_tokens BIGINT, output_tokens BIGINT, cache_read_tokens BIGINT, cost_usd DOUBLE,
  batch_id VARCHAR, custom_id VARCHAR, dossier_version INTEGER, started_at TIMESTAMP, ended_at TIMESTAMP, error VARCHAR);
CREATE TABLE IF NOT EXISTS dossier_claims (
  symbol VARCHAR, as_of DATE, claim_id VARCHAR, section VARCHAR, text VARCHAR, citations_json VARCHAR,
  quote VARCHAR, table_ref_json VARCHAR, verified BOOLEAN, verify_method VARCHAR, verify_score DOUBLE,
  verifier_note VARCHAR, run_id VARCHAR, PRIMARY KEY (symbol, as_of, claim_id));
CREATE TABLE IF NOT EXISTS web_sources (
  src_id VARCHAR PRIMARY KEY, symbol VARCHAR, run_id VARCHAR, url VARCHAR, title VARCHAR, published DATE,
  source_kind VARCHAR, sha256 VARCHAR, text_path VARCHAR, fetched_at TIMESTAMP, as_of DATE, visible_from DATE);
CREATE TABLE IF NOT EXISTS news_items (
  symbol VARCHAR, sha1 VARCHAR, published DATE, title VARCHAR, source VARCHAR, url VARCHAR, fetched_at TIMESTAMP,
  as_of DATE, visible_from DATE, PRIMARY KEY (symbol, sha1));
```

`migrations.sql` (idempotent, run after `schema.sql` by `init_schema`):

```sql
ALTER TABLE results_calendar ADD COLUMN IF NOT EXISTS xbrl_url VARCHAR;
ALTER TABLE results_calendar ADD COLUMN IF NOT EXISTS seq_id VARCHAR;
ALTER TABLE results_calendar ADD COLUMN IF NOT EXISTS type_sub VARCHAR;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extract_status VARCHAR;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS schema_version INTEGER;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS engine_rating VARCHAR;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS llm_view VARCHAR;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS run_id VARCHAR;
```

## Appendix B — File structure (one line each)

```
pyproject.toml                        0.2.0; + anthropic>=1.0 lxml>=5.3 networkx>=3.4 feedparser>=6.0.11 pdfplumber>=0.11; optional extra: docling
.env.example / eqr/config.py          + EQR_ERP_PCT EQR_LLM_MONTHLY_USD EQR_LLM_PER_RUN_USD EQR_CLAUDE_VERIFIER_MODEL EQR_WEB_ALLOWED_DOMAINS EQR_RESEARCH_TOP_N EQR_DOC_PARSER
eqr/cli.py                            + xbrl, filings2, metrics, rate, news, research, research-collect; sub-apps graph, docs
eqr/store/schema.sql                  + 19 tables (Appendix A)
eqr/store/migrations.sql              idempotent ALTER TABLE … ADD COLUMN IF NOT EXISTS for existing tables
eqr/store/db.py                       init_schema runs schema.sql then migrations.sql
eqr/store/pit.py                      + xbrl_as_of, holders_as_of, pledges_as_of, ratings_as_of, insider_as_of, graph_edges_as_of
eqr/spine/nse_api.py                  both results feeds return xbrl_url, seq_id, type_sub (placeholder "/-" → NULL)
eqr/spine/xbrl.py                     XBRL parser (in-bse-fin 2018/2020, in-capmkt 2026, bank variant), crore scaling, first-seen loader, sweep
eqr/spine/nse_filings.py              credit ratings, board meetings, insider ledger, SHP XBRL → holders_named/pledges, name→symbol matcher
eqr/spine/quality.py                  + xbrl_screener_agreement, xbrl_freshness, filings_freshness
eqr/fundamentals/base.py              Metric (value+provenance), MetricSet, Inputs, load_inputs, percentile_grouped, is_financial
eqr/fundamentals/forensic.py          12 Ambit-style checks, Beneish M, Sloan, Mohanram G (partial), bank forensic variant
eqr/fundamentals/quality.py           QMJ-style profitability/stability/safety/payout, 10y ROCE, reinvestment
eqr/fundamentals/valuation.py         reverse-DCF implied growth, own 10y bands, peer multiples, P/B vs ROE, expected-return band
eqr/fundamentals/governance.py        pledge, insider flow, holder trends, auditor events, audit opinion, rating migration, adverse news, surveillance
eqr/fundamentals/sector_kpis.py       bank/NBFC KPIs from XBRL; others UNKNOWN
eqr/fundamentals/build.py             build_metrics → fund_metrics (monthly PIT)
eqr/rating/pillars.py                 component tables per pillar (metric, sign, kind, weight), financial variants
eqr/rating/engine.py                  pure engine: pillar scores, gates, composite, notch, confidence, manifest, DATA_ERROR
eqr/rating/ledger.py                  ratings storage, append-only rating_ledger, maturity scoring
eqr/rating/calibrate.py               PIT monthly backtest, forward returns, buckets, IC, Brier, NW t-stats, walk-forward, holdout
eqr/rating/acceptance.py              pre-registered BAR (§3.5)
eqr/rating/report.py                  calibration report md/json/csv → data/reports/calibrate-*/
eqr/research/docstore.py              %PDF check, layout-mode text, extract_status, per-kind caps
eqr/research/docparse.py              page split, regex section locator, pdfplumber tables, note extractors → doc_sections
eqr/research/news.py                  Google News RSS (feedparser) → news_items
eqr/research/llm.py                   LLM protocol; AnthropicLLM (structured outputs, caching, batches, web tools, budget guard); CliLLM; FakeLLM
eqr/research/schema.json / schema.py  dossier schema v2 (v1-compatible), citation grammar doc/table/web, quote rule
eqr/research/verify.py                deterministic quote/table/web verifier; strike + reject rules
eqr/research/pack.py                  pack v2 with token budget (metrics, rating, graph, filings, news, sections)
eqr/research/research.py              orchestrator run_research(); batch submit/collect; research_runs; fan-in guard
eqr/research/dossier.py               render_markdown v2; run_dossier kept as v1 wrapper
eqr/graph/model.py                    Node/Edge dataclasses, node_id normalisation, alias lookup
eqr/graph/store.py                    upsert nodes/edges (identity), lane-scoped clear, close_edges, load_graph(as_of) → nx.MultiDiGraph
eqr/graph/builders.py                 industry/sector/index, promoters (SHP), auditors (XBRL/AR), rating agencies, subsidiaries (AOC-1)
eqr/graph/features.py                 promoter-group components, contagion, auditor risk, sector migration → graph_features
eqr/graph/export.py / layout.py       GraphML/JSON export; server-side layout → inline SVG
eqr/surfaces/*                        queries, app routes, templates (symbol Research section, ratings, graph, doc), advisor client, digest
deploy/mac/jobs.py, deploy/mac/launchd/com.eqr.research.plist, deploy/systemd/*.service
tests/test_xbrl.py test_nse_filings.py test_fundamentals_{base,forensic,quality_valuation,governance,build}.py
tests/test_rating_{engine,ledger,calibrate}.py test_layering.py test_docstore.py test_docparse.py test_graph.py
tests/test_research_{llm,verify,orchestrator}.py test_news.py test_surfaces_research.py + fixtures (xbrl_*.xml, shp_sample.xml,
      credit_rating_sample.json, pit_sample.json, board_meetings_sample.json, ar_pages_sample.txt, transcript_pages_sample.txt, news_rss_sample.xml, dossier_v2_good.json)
```

## Appendix C — Job schedule after Phase 7

`deploy/mac/jobs.py` chains (launchd execs `.venv/bin/python` directly, as today):

```python
"refresh":      [["refresh"], ["reference", "--from", d-45], ["filings2", "--daily"], ["xbrl", "--recent"],
                 ["rate", "--universe", "--publish"]],
"fundamentals": [["fundamentals", "--rate", "1.5"], ["filings2", "--universe-insider"], ["features"], ["metrics"],
                 ["docs", "parse", "--recent", "14"], ["graph", "build"], ["graph", "features"],
                 ["rank", "--sleeve", "L"], ["rank", "--sleeve", "S"], ["rate", "--universe", "--publish"]],
"digest":       [["digest", "--send"]],
"research":     [["research", "--batch", "--held", "--top", "40"], ["research-collect", "--latest", "--wait", "90"]],
```

New `deploy/mac/launchd/com.eqr.research.plist` (Sunday 03:00 local); `install-mac.sh` `LABELS` gains `com.eqr.research`; the systemd units gain the same steps except that there is no research unit on the VM (Claude runs only on the Mac). `tests/test_launchd.py` gains the new label and chain assertions.

Advisor contract after T7.3: `/advisor/v1/evidence/{symbol}` carries `rating: {as_of, rating, verdict, score, confidence, gated, validated} | null`; `advisor_client.evidence_line` zeroes the eqr points (status FAIL) only when a VALIDATED engine says SELL, leaves them unchanged for an unvalidated engine or a missing block, and never adds points or blocks — the caller's gates stay the caller's.

Digest after T7.4: for held names, rating changes since the previous rating date (`SYM: BUY → HOLD (score 71 → 58, gate PLEDGE_GT_50)`), newly triggered gates, and research completed in the last day (`SYM verified 27/29 claims, LLM view BUY vs quant HOLD`).

## Appendix D — Design critique (what the design pass changed versus the first brief, and why)

- **Rating engine and calibration moved ahead of XBRL, documents, graph and LLM work.** Engine r1 runs on data already in the store (1.02M screener statement rows, 117 monthly feature dates, shareholding, surveillance) and can be calibrated over 2017→ in week two while the ~30-hour XBRL backfill runs in the background; r2 adds the forensic pillar, r3 adds graph and qualitative, each calibrated separately like the sleeves.
- **docling rejected as the default parser.** Measured pypdf quality on the 14 stored RELIANCE documents is good for transcripts and annual reports; only image-heavy presentations are poor. Default = pypdf + regex section locator + pdfplumber on the located pages; docling is an optional extra gated on spike S0.8. pdfplumber adequacy is not yet measured (S0.7).
- **Two LLM passes collapsed into one structured call; verification is deterministic by default.** Anthropic document citations are incompatible with structured outputs, so every document claim carries a verbatim quote checked against `doc_sections.text`, table claims carry a `table_ref` checked against the pack, and web claims must cite harvested URLs. The Sonnet 5 verifier (fresh context, strike-only) runs in `--deep` only.
- **Graph-risk pillar is deterministic contagion only.** LLM-extracted edges are stored, displayed and exported but do not score until coverage ≥ 50% of the universe and a calibration shows IC; Cohen–Frazzini spillover is a later experiment.
- **Pledges come from shareholding-pattern XBRL, not the NSE pledge endpoint** (empty in every parameter shape). The same file supplies named promoter holders for the graph.
- **Insider trades are a forward-only ledger** (the feed ignores date windows). **Credit ratings** come from the market-wide daily feed matched by ISIN then normalised name, history from about September 2023; rationale PDFs keep arriving through announcements.
- **XBRL scope stated honestly:** real XBRL from Q4 FY2018; survivorship closes from 2018 only.
- **Damodaran reduced to two config numbers** (`EQR_ERP_PCT`, existing `EQR_RISK_FREE_PCT`) plus `beta_250`; Parallel.ai dropped; the expected-return band is informational, never a score input.
- **Invariants added as tests:** layering (no upward imports into rating/research/graph/anthropic), qualitative weight ≤ 0.20, advisor rating block can only zero points.

## Appendix E — Evidence log from the read-only probes (2026-09-14, Mac residential IP, existing cookie warm-up; nothing written to `data/`)

| # | Fact | Status | Evidence |
|---|---|---|---|
| E1 | Integrated filing rows carry `xbrl`/`ixbrl` URLs | observed | `/api/integrated-filing-results` row keys include `xbrl`, `ixbrl`, `seq_Id`, `type_Sub`, `revised_Date`; sample `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1715237_14082026114951_WEB.xml` |
| E2 | Legacy results rows carry `xbrl` | observed | `/api/corporates-financial-results` row keys include `bank`, `format`, `xbrl`; sample `INDAS_106475_1130973_20052024093523.xml` |
| E3 | XBRL history starts 2018 | observed | May windows: 2016 rows 615 / real XBRL 0; 2017 279 / 0; 2018 209 / 166; 2019 764 / 755; 2020 173 / 173; 2021 501 / 501; 2023 1271 / 1271; 2017 sample URL ends in `/-` |
| E4 | Three namespaces + bank variant | observed | `in-bse-fin` 2018-03-31 (2018, 2020 files), `in-bse-fin` 2020-03-31 (2024 file), `in-capmkt` 2026-01-31 (2026 file), `in-capmkt-ent` (bank file); core P&L tags present in all; `TradeReceivablesCurrent`, `Inventories`, `SegmentRevenue` only in the annual file. Full tag map = S0.1 (inferred that 2018 and 2020 share core localnames) |
| E5 | Annual/half-yearly XBRL carries BS, CF, auditor, opinion | observed | BELRISE FY2026 consolidated: 242 distinct tags incl. `Assets`, `AuditorsFirmName`, `BorrowingsCurrent/Noncurrent`, `CashFlowsFromUsedInOperatingActivities`, `DeclarationOfUnmodifiedOpinion…`, `Goodwill`, `Inventories`; Q1 file: 62 facts, 2 contexts |
| E6 | Bank XBRL carries KPIs | observed | ESAFSFB FY2026: `CET1Ratio`, `GrossNonPerformingAssets`, `PercentageOfGrossNpa`, `PercentageOfNpa`, `ReturnOnAssets`, `Advances`, `Deposits`, provisions |
| E7 | Backfill size | count observed, bytes inferred | 106,825 distinct (symbol, period_end, consolidated) since 2018-03-31 in `results_calendar`; file sizes seen 10 KB–675 KB; "≈ 5 GB, ≈ 30 h at 1 req/s" is an estimate |
| E8 | 333 filing symbols absent from `instruments` | observed; "delisted" inferred | `SELECT count(DISTINCT r.symbol) FROM results_calendar r LEFT JOIN instruments i USING (symbol) WHERE i.symbol IS NULL AND r.period_end >= '2018-03-31'` → 333; renames not separated |
| E9 | Pledge endpoint returns no data | observed | `/api/corporate-pledgedata` with index only, five symbols, date windows → HTTP 200, `data` empty every time |
| E10 | Insider feed ignores date windows; latest 20 per symbol works | observed | `/api/corporates-pit?index=equities&symbol=RELIANCE` → 20 rows with `acqName`, `anex 7(2)`, `tdpTransactionType`, `xbrl`; every `from_date/to_date` shape → 0 rows; `period=1M` → 20 rows, lexicographically sorted |
| E11 | SHP XBRL has holder names and %; pledge counts not observed | observed / not observed | `/api/corporate-share-holdings-master` rows carry `xbrl` (`SHP_1694620_…xml`, 510 KB); namespace `in-bse-shp` 2025-10-31; tags `NameOfTheShareholder`, `NumberOfShares`, `ShareholdingAsAPercentageOfTotalNumberOfShares`, `NumberOfTheLockedInShares`, `WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged`; RELIANCE has no pledges, so a per-holder pledged-count tag needs S0.2 on a pledged name |
| E12 | Credit-rating feed shape, NOTLISTED rows, history start | observed; start month inferred | `/api/corporate-credit-rating` → 440 rows regardless of symbol; keys `NameOfCRAgency`, `CreditRating`, `RatingAction`, `Outlook`, `DateofCR`, `CreditRatingEarlier`, `ISIN`, `Symbol`, `XbrlFileName`, `AppID`; Jan-2024 window 405 rows (178 no symbol, 103 `NOTLISTED`, 80 `Not Listed`); 2019–Mar-2023 windows 0 rows, Sep-2023 1,200 rows |
| E13 | Board-meeting feed works per symbol and market-wide | observed | keys `bm_symbol`, `bm_date`, `bm_purpose`, `bm_desc`, `bm_timestamp`, `attachment`, `ixbrl`; 1–15 Jul 2026 market-wide → 274 rows |
| E14 | pypdf quality good; pdfplumber/docling not measured | observed / inferred | annual reports 187 and 174 pages: prose-line share 0.69, 112 and 97 section-heading hits; transcripts 0.90–0.93; one presentation extracted 6 words from 3.3 MB (`%PDF-1.7`, image-only); `pdfplumber`, `docling`, `fitz` not installed |
| E15 | venv state; PyPI JSON blocked | observed | `lxml 6.1.3`, `pydantic 2.13.5`, `bs4 4.15.0` present; `networkx`, `anthropic`, `feedparser` missing; Python 3.13.14; `requests` to pypi.org failed with a self-signed certificate in the chain → S0.5 uses `uv` |
| E16 | nsearchives cookie gating | inferred, not tested | all probes ran on a warmed session; `docs/DATA_SOURCES.md` and the bhavcopy loader say archives need no cookies; `curl` without cookies is the S0.1 test |
| E17 | Store facts | observed | instruments 2,568; prices_daily 5,448,215; statements 1,018,907; statement_revisions 0; shareholding 192,677; results_calendar 128,885 (105,162 legacy / 23,723 integrated); announcements 3,319 (one symbol); documents 14; features 98,186 rows over 117 dates; universe 1,208 names on 2026-09-11; dossiers 0 |
| E18 | Claude API facts | documentation, to be observed in S0.6 | Opus 5 $5/$25, Sonnet 5 $2/$10, Haiku 4.5 $1/$5 per MTok; structured outputs via `output_config.format`; citations incompatible with structured outputs (400); Batches at 50%; `web_search_20260209` / `web_fetch_20260209` with `max_uses`, `allowed_domains`; cache reads ≈ 0.1×, writes ≈ 1.25× |
