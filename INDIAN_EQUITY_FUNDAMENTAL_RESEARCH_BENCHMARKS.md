# Indian-Equity Fundamental-Research Benchmarks

> Competitive code audit and implementation roadmap for Project Research Bot (`eqr`).
> Research snapshot: 14–15 September 2026 (IST). This is an engineering benchmark, not investment advice.

## 1. Executive summary & landscape

### Bottom line

There is no mature open-source project that combines authoritative NSE/BSE ingestion, point-in-time (PIT) statements, India-specific forensics, multi-method valuation, sector routing, filing/concall evidence, and walk-forward validation. The strongest designs are composable parts:

1. **Evidence-grade ingestion:** Fundamental-Screener, Ananke, Disclosed, jugaad-data.
2. **Formula fidelity:** Bharat-equity-skills.
3. **PIT ranking:** magic-formula-pit.
4. **Governed valuation:** AnalystCollective.
5. **Document acquisition and verification:** Disclosed, screener-mcp, equity-research-india.

`eqr` already exceeds every audited repository on the *integrated* deterministic path: it has PIT readers, six sector profiles, a six-pillar rating engine, 29 catalogued red flags, confidence and manifest machinery, multi-model valuation, decision surfaces, and walk-forward infrastructure. The roadmap must therefore **not** invent placeholder “forensic” or “valuation” modules. Those modules exist. The real work is to populate authoritative data, correct incomplete formula implementations, expose already-computed outputs, add filing evidence, and validate any new score path.

### What the live `eqr` checkout already has

| Area | Live implementation | Confirmed limitation |
|---|---|---|
| PIT statements | `eqr/store/pit.py` enforces `visible_from <= as_of` and prefers consolidated facts per line item | Per-line fallback can mix consolidated and standalone facts within one period; it is not an atomic basis choice |
| Screener spine | Consolidated-first fetch, standalone fallback, raw dated HTML cache, filing-date stamping | Screener is restated derived data; the official site says it offers CSV export, not an API |
| XBRL | `eqr/spine/xbrl.py` parses legacy `in-bse-fin`, newer `in-capmkt`, and bank `in-capmkt-ent`; stores contexts, revisions, source URLs and hashes; `eqr xbrl --backfill-from` already exists | Production `statements_xbrl` and `xbrl_filings` both have 0 rows; only 4 of 128,886 `results_calendar` rows currently contain an XBRL URL |
| Forensics | Sloan accruals, CFO/PAT, other-income dependence, cash-tax gap, working-capital-day changes, Beneish-style score and sector exclusions | GMI/AQI are proxies, SGAI is absent, the prior-year score is unimplemented, and optional indices are held in a positional list that can shift coefficients |
| Solvency/quality | EM-adjusted Altman Z″ and a seven-signal Piotroski implementation | Piotroski lacks current-ratio improvement and gross-margin improvement; Altman working capital is proxied until XBRL is populated |
| Valuation | WACC, reverse DCF, 5-year growth plus 5-year fade DCF, base/bull/bear, own-band EV/EBITDA and P/FCF, EPV, justified P/B, DDM, MoS and expected-return band | Expected-return band is stored but not shown on the one-pager; reverse-DCF diagnostics are thin; `MCAP_NOT_SPLIT_INVARIANT` remains open for sleeve features even though the fundamentals valuation series was corrected |
| Sector adaptation | GENERAL, BANK, NBFC_FIN, IT_SERVICES, PHARMA and CYCLICAL profiles; bank/NBFC metric swaps | XBRL-dependent CET1/PCR/current-liquidity fields are unavailable in production |
| Flags | 29 flags catalogued: 9 HARD, 12 SOFT and 8 WATCH, including pledge tiers, audit qualification, Beneish, cash divergence and surveillance; 27 currently have evaluator branches | Pledge, insider, named-holder, credit-rating and board-meeting inputs are empty; `REGULATORY_FRAUD` and `VALUATION_DISPERSION_GT_50` are catalogued but cannot fire because they have no evaluator branches, while `FORENSIC_CASH_DIVERGENCE` omits its documented prior-year condition |
| Research | Document store, dossier schema, citation-ID/page checks, rejection path, r3-only `with_qual` variant | 14 documents cover one symbol; `doc_sections` and `dossiers` have 0 rows; no MD&A/concall, RPT or contingent-liability extractor; dossier packs omit source URLs |

Live database snapshot used for this report:

- `statements`: 1,018,907 rows; `results_calendar`: 128,886 rows across 2,743 symbols.
- `announcements`: 3,319 rows, but for only one symbol; `documents`: 14 rows, also a one-symbol pilot.
- `statements_xbrl`, `xbrl_filings`, `pledges`, `insider_trades`, `board_meetings`, `holders_named`, `credit_ratings`, `doc_sections`, `dossiers`, `web_sources`, and `news_items`: 0 rows.

This corrects four stale assumptions in the supplied baseline: announcements are not literally empty, the flag catalogue now contains 29 rather than 22 flags, consolidated preference does exist at the query layer, and the XBRL backfill CLI plus expected-return calculation already exist. Their coverage or exposure remains incomplete.

### Audit coverage and verification caveat

- **Fan-in:** four pillar audits returned plus the local `eqr` explorer: **5/5**.
- **Candidate coverage:** ingestion 10/10, ratios/forensics 10/10, valuation 8/10, filing/NLP 10/10: **38/40 candidate slots**, covering **34 distinct repositories plus two separately audited in-repository skills (36 distinct audited artifacts)**. “light-saber screener” and “DCF-Financial-Modelling” could not be resolved after exact-name, variant-name, repository and code searches; no unrelated project was substituted.
- **PyPI:** direct JSON verification was **0/7** because all seven registry requests returned reproducible HTTP 503 block pages in this environment. Repository metadata declares three associations (`jugaad-data`, `nsepython`, `screener-mcp`), reported separately as **3/7 upstream-declared, not registry-verified**.
- Initial discovery and most code fetches ran through the GitHub API on **2026-09-14**. The final URL/star/push-date recheck crossed midnight and ran on **2026-09-15 IST**. Stars are included only as adoption context, not a quality score.
- Claims below distinguish inspected code from README claims and closed remote services. “No licence” means no reusable permission was established, even if source is publicly visible.
- Official/public anchors were separately checked for [Screener export policy](https://support.screener.in/article/28-export-screen-results), [BSE XBRL filing categories](https://www.bseindia.com/corporates/xbrldetails), [NSE annual-report filings](https://www.nseindia.com/companies-listing/corporate-filings-annual-reports-xbrl), and [SEBI promoter-encumbrance disclosure](https://www.sebi.gov.in/legal/circulars/aug-2019/disclosure-of-reasons-for-encumbrance-by-promoter-of-listed-companies_43837.html).

### Landscape conclusions

1. **The moat is provenance, not another scraper.** Keep raw bytes, source URL, exchange publication time, retrieval time, SHA-256, schema/parser version, context, basis and revisions.
2. **Most “AI research” repos are prompts or bridges.** An MCP transport is not evidence that its proprietary server’s DCF, forensic score or PIT claims are reproducible.
3. **README breadth inversely correlates with auditability.** The best components fail closed, expose missingness and publish assumptions.
4. **India-specific governance is the largest OSS gap.** Pledge, SAST/PIT trades, auditor events, RPTs, guarantees and contingencies are rarely joined to financial statements.
5. **BFSI must be routed, not patched.** Beneish, Altman, FCF and industrial working-capital metrics should be NA for banks/NBFCs; regulatory capital, asset quality, provisioning, funding and P/B or residual-income methods replace them.
6. **Do data work first.** Until XBRL and events are populated, adding score weights creates precision without evidence.

Recommended order: **XBRL registry/backfill and basis integrity → pledge/insider/SAST events → canonical forensic calculators and flags → valuation exposure → verified documents/concall → pre-registered Magic Formula variant.**

## 2. Deep audit of the top 10 repositories

The shortlist favors reusable engineering evidence over stars or feature claims. Metadata below was rechecked through `gh api repos/OWNER/REPO`; code links pin the inspected revision.

### 2.1 Fundamental-Screener — dvygo / Deshik Narasimha

- **Repository:** [dvygo/Fundamental-Screener](https://github.com/dvygo/Fundamental-Screener) — 0 stars; pushed 2026-08-26; BSD-3-Clause.
- **Focus and sources:** local ELT for NSE/BSE daily drops, NSE/SEBI filing CSVs and XBRL links, Screener company pages/search, LiveMint and Rupeevest, with DuckDB/Parquet and optional MinIO WORM storage.
- **Strengths:** raw-file SHA-256 manifest; idempotent object keys; filing split by dissemination/broadcast time; URL-or-row-hash dedupe; cached Screener HTML; three attempts; explicit 403/429 backoff; four-second pacing. The [ingestion manifest](https://github.com/dvygo/Fundamental-Screener/blob/2ccb36c2f323783a086ed0ecee8e2a81e351e9f3/src/python/ingest.py#L100-L134) and [filing splitter](https://github.com/dvygo/Fundamental-Screener/blob/2ccb36c2f323783a086ed0ecee8e2a81e351e9f3/src/python/split_filings.py#L42-L86) are the most transferable pieces.
- **Scoring:** HUNT is an event-prioritisation score (insider buys, new highs/lows, news, actions and movers), not a fundamental valuation score.
- **Notable pattern:**

```python
digest = sha256(raw_bytes)
manifest = {source_url, object_key, byte_count, digest, ingested_at}
if object_key_exists: skip_without_overwrite()
```

- **Limits:** source rights vary; a date folder is not a full PIT model; current Screener-derived fundamentals remain restated. Adopt the immutable-manifest and retry patterns, not its entire source mix.

### 2.2 Ananke — prizrakresearch

- **Repository:** [prizrakresearch/ananke](https://github.com/prizrakresearch/ananke) — 1 star; pushed 2026-06-17; **no licence found**.
- **Focus and sources:** BSE `Result_Arch_ng` registry, BSE XBRL downloads, context-aware Ind-AS parsing and stitched financial tables.
- **Strengths:** retains raw XML; maps local filenames to source links; skips exact repeats; preserves changed URLs as duplicates; carries filing time and instant/duration contexts; adds 0.5–3 second random delay. See its [registry fetch](https://github.com/prizrakresearch/ananke/blob/a53a1eb827412fecfeeb23570d87fe7cd00ed309/ingestion/bse_xbrl_registry.py#L6-L110) and [download manifest](https://github.com/prizrakresearch/ananke/blob/a53a1eb827412fecfeeb23570d87fe7cd00ed309/ingestion/downloader.py#L131-L180).
- **Scoring:** none.
- **Notable pattern:** prefer the filed standalone XBRL link, fall back to consolidated only when needed, but persist the chosen basis and original registry row.
- **Limits:** the parser strips namespaces to local names and uses manual mappings, which is unsafe across taxonomy versions/extensions. It lacks an explicit as-of query model and reuse permission. Use it as an ingestion design reference only.

### 2.3 Disclosed — pruthvi-itribe / Pruthvi Raj

- **Repository:** [pruthvi-itribe/disclosed](https://github.com/pruthvi-itribe/disclosed) — 1 star; pushed 2026-08-20; MIT licence file, although root package metadata says `UNLICENSED`.
- **Focus and sources:** low-latency NSE/BSE corporate-filings intelligence: announcement polling, historical drain, Mongo persistence, attachment fetch, PDF/Docling extraction, LLM-proposed claims and deterministic evidence verification.
- **Strengths:** store-first/no-hole cursor; idempotent sequence IDs; cached and coalesced NSE session refresh; typed attachment failures; 64 MiB cap; OCR escalation for no-text PDFs; exact-span claim gate; refusal records; adversarial evaluation that mutates words, digits, figures and periods. The [poll/drain contract](https://github.com/pruthvi-itribe/disclosed/blob/76cf5905d05c6e4e08bec292e0aaf5163c863ecb/apps/ingest/src/poller/poller.service.ts#L89-L134), [claim verifier](https://github.com/pruthvi-itribe/disclosed/blob/76cf5905d05c6e4e08bec292e0aaf5163c863ecb/libs/filings/src/logic/claim-verify.ts#L17-L45) and [measurement harness](https://github.com/pruthvi-itribe/disclosed/blob/76cf5905d05c6e4e08bec292e0aaf5163c863ecb/tools/claims/measure-claim-gate.ts#L124-L217) are benchmark-quality patterns.
- **Scoring:** deliberately none; it measures extraction coverage, acceptance and refusal rather than emitting investment ratings.
- **Notable pattern:**

```text
LLM proposal → exact source-span match → number/period checks
             → VERIFIED or persisted REFUSED(reason)
```

- **Limits:** not a statement/valuation engine or dedicated concall parser; Mongo/Redis/Docling stack is heavy; latency claims were not independently reproduced. Borrow the refusal-first boundary and tests.

### 2.4 Bharat-equity-skills — Yash Sharma

- **Repository:** [sharma23yash-oss/Bharat-equity-skills](https://github.com/sharma23yash-oss/Bharat-equity-skills) — 0 stars; pushed 2026-08-31; MIT.
- **Focus and sources:** test-backed calculators and Markdown output in Indian annual-report vocabulary. It intentionally leaves acquisition to the caller.
- **Strengths:** canonical Beneish coefficients, Piotroski nine signals, EM-adjusted Altman Z″, five-step DuPont, missing-input propagation, BFSI exclusions and a transparent India red-flag register. The [coefficient placement](https://github.com/sharma23yash-oss/Bharat-equity-skills/blob/199cbdc/bharat_scores/scores.py#L124-L136) correctly keeps `TATA=+4.679` and `LVGI=-0.327`.
- **Scoring:** F-score bands; M-score and Z″ thresholds; policy alerts for CFO/PAT, pledge, RPT/revenue, contingencies/equity, receivable growth, other-income dependence, tax, interest coverage, CWIP and audit changes.
- **Notable formula:**

```text
M = -4.84 + .920 DSRI + .528 GMI + .404 AQI + .892 SGI
    + .115 DEPI - .172 SGAI + 4.679 TATA - .327 LVGI
```

- **Limits:** very young; no source provenance/downloader; AQI needs explicit marketable-securities handling; thresholds are useful triage defaults, not India-calibrated findings. Best formula reference, not an ingestion solution.

### 2.5 magic-formula-pit — Aashish Bohra

- **Repository:** [quantxaashish/magic-formula-pit](https://github.com/quantxaashish/magic-formula-pit) — 0 stars; pushed 2026-09-08; MIT.
- **Focus and sources:** NSE/BSE Greenblatt ranking, baskets and walk-forward backtest using an exchange/AMFI universe, Screener fundamentals and price/share history.
- **Strengths:** explicit formula variants; invalid-value exclusions; listing-date clipping; fiscal-year plus conservative 60-day availability proxy; cache/rate limiting; anomaly logs; global and cap-bucket ranks; turnover buffer. The project candidly refuses to treat current scraped market cap as historical EV. See [formula definitions](https://github.com/quantxaashish/magic-formula-pit/blob/fbbffcc/src/magicformula/formulas.py#L26-L64), [ranking](https://github.com/quantxaashish/magic-formula-pit/blob/fbbffcc/src/magicformula/ranker.py#L38-L72), and [PIT eligibility](https://github.com/quantxaashish/magic-formula-pit/blob/fbbffcc/src/magicformula/backtest.py#L80-L134).
- **Scoring:**

```text
EBIT = operating profit - depreciation
EV   = market cap + debt - cash - liquid investments
EY   = EBIT / EV
ROC  = EBIT / (net working capital + net fixed assets)
rank = rank_desc(EY) + rank_desc(ROC)
```

- **Limits:** no DCF or MoS; exact filing dates are incomplete; Screener rights/restatement risk remains. Adopt as a **pre-registered experimental rank variant**, never as an invisible change to the current sleeve score.

### 2.6 AnalystCollective — Alyosha28

- **Repository:** [Alyosha28/AnalystCollective](https://github.com/Alyosha28/AnalystCollective) — 3 stars; pushed 2026-07-21; MIT.
- **Focus and sources:** general/global Damodaran-style valuation toolkit. Inputs are user supplied; it has no NSE/BSE connector.
- **Strengths:** revenue, margin and cost-of-capital glides; reinvestment tied to sales-to-capital; terminal reinvestment tied to growth/ROC; debt, cash, minority and non-operating bridges; failure-probability mix; source-tier/freshness validation; DCF, reverse DCF, Monte Carlo, SOTP and comps. See [two-stage FCFF](https://github.com/Alyosha28/AnalystCollective/blob/5318a2e/scripts/dcf_valuation.py#L132-L208), [bounded reverse solver](https://github.com/Alyosha28/AnalystCollective/blob/5318a2e/scripts/reverse_dcf.py#L25-L68), and [uncertainty-linked MoS](https://github.com/Alyosha28/AnalystCollective/blob/5318a2e/scripts/monte_carlo.py#L57-L107).
- **Scoring/output:** bounded bisection solves price-implied terminal revenue, margin, sales-to-capital or initial CoC; endpoints return no-solution. Monte Carlo sets a required MoS from distribution dispersion:

```text
required_MoS = clip(0.5 × (P90 - P10) / median, 15%, 50%)
```

- **Limits:** method reference rather than India coverage. Its best contribution is solver governance and provenance gating.

### 2.7 screener-mcp — Logesh Ramasamy

- **Repository:** [LogeshR15/screener-mcp](https://github.com/LogeshR15/screener-mcp) — 13 stars; pushed 2026-09-12; MIT.
- **Focus and sources:** MCP over Screener company/search pages plus NSE announcements and annual reports.
- **Strengths:** persistent Screener login/CSRF session; login-redirect detection; URL-hashed PDF cache; persistent Chroma index; NSE browser-session warm-up and annual-report attachment discovery. The [Screener session](https://github.com/LogeshR15/screener-mcp/blob/cf2231ed5c8be34d285f3b73ed39526c3d16f9c9/src/screener_mcp/client.py#L32-L119) and [NSE annual-report client](https://github.com/LogeshR15/screener-mcp/blob/cf2231ed5c8be34d285f3b73ed39526c3d16f9c9/src/screener_mcp/core/nse_client.py#L33-L86) are useful small adapters.
- **Scoring:** no proprietary numeric score in inspected code.
- **Notable route:** `/api/annual-reports?index=equities&symbol=SYMBOL`, after warming an NSE session. This is observed code, not a documented exchange API contract.
- **Limits:** no global rate governor or PIT source model; public vs authenticated Screener capability differs; remote MCP needs authentication controls. Keep as an optional document adapter, not source-of-record.

### 2.8 jugaad-data — jugaad-py

- **Repository:** [jugaad-py/jugaad-data](https://github.com/jugaad-py/jugaad-data) — 572 stars and 208 forks; pushed 2026-08-25; custom YOLO/public-domain-style licence, not a standard OSI licence (GitHub API reports no SPDX).
- **Focus and sources:** broad unofficial NSE historical/live equities, derivatives and indices plus RBI data; some BSE live routes.
- **Strengths:** argument-keyed persistent historical cache, locked short-lived live cache, browser-like sessions, archive/report endpoints and integrated filing routes. Its [live client](https://github.com/jugaad-py/jugaad-data/blob/7ae415e5ed5cbbe805bcc43d8bbb4b4ab97c6000/jugaad_data/nse/live.py#L7-L30) and [integrated-filings pagination](https://github.com/jugaad-py/jugaad-data/blob/7ae415e5ed5cbbe805bcc43d8bbb4b4ab97c6000/jugaad_data/nse/live.py#L245-L280) are valuable endpoint references.
- **Scoring:** none.
- **Notable pattern:** permanent cache for historical calls and approximately five-second live caching reduce exchange load.
- **Limits:** no revision provenance or as-of/universe model; a permanent pickle cache can hide corrections; undocumented exchange routes can break. Use route/header/cookie patterns behind `eqr`-owned contracts, not its cache semantics verbatim.

### 2.9 promoter-watch — Bhupendra Tale

- **Repository:** [bhupendra05/promoter-watch](https://github.com/bhupendra05/promoter-watch) — 0 stars; pushed 2026-06-01; `pyproject.toml` says MIT but no licence text was present and GitHub reports no SPDX.
- **Focus and sources:** BSE shareholding and bulk-deal adapter plus alert logic.
- **Strengths:** real BSE public-endpoint parsing of shareholding, bulk deals and pledged/encumbered percentage; explicit alert reasons. See [BSE field mapping](https://github.com/bhupendra05/promoter-watch/blob/b859e41/promoter_watch/bse.py#L46-L131) and [threshold logic](https://github.com/bhupendra05/promoter-watch/blob/b859e41/promoter_watch/alerts.py#L10-L70).
- **Scoring:** pledge bands at 15%, 30% and 50%; bulk-sale alerts above ₹50 crore and ₹200 crore aggregate; any pledge event high and three or more sells moderate.
- **Notable pattern:** keep raw percentage-of-promoter-holding distinct from percentage-of-total-capital and attach the rule to every alert.
- **Limits:** fetches only latest quarter (`qtrid=0`); no native pledge history, shown insider fetch, SAST, auditors, RPTs, contingencies or sector routing. Reimplement the adapter after endpoint/licence review.

### 2.10 equity-research-india — cdraarsh

- **Repository:** [cdraarsh/equity-research-india](https://github.com/cdraarsh/equity-research-india) — 2 stars; pushed 2026-05-09; MIT.
- **Focus and sources:** small Indian qualitative-research skill with Screener parsing and annual-report/concall slicing.
- **Strengths:** parses financial tables, annual-report links, concall transcript/PPT/recording/summary URLs; uses `pdftotext -layout`; detects too-short text; explicitly routes image PDFs to `ocrmypdf`; slices MD&A and call sections with heading/speaker heuristics. See [concall link manifest](https://github.com/cdraarsh/equity-research-india/blob/89e9668/scripts/parse_screener.py#L300-L329), [PDF/OCR gate](https://github.com/cdraarsh/equity-research-india/blob/89e9668/scripts/slice_pdf.py#L84-L95), and [guidance-versus-delivery rubric](https://github.com/cdraarsh/equity-research-india/blob/89e9668/references/concall-analysis.md#L22-L33).
- **Scoring:** no deterministic score; prompts ask for evidence-oriented qualitative output.
- **Notable pattern:** preserve all document variants and separate prepared remarks from Q&A before model extraction.
- **Limits:** OCR is a manual instruction, tables are not validated, outputs are loose dictionaries, and there is no hash/page-span verifier, automated evaluation or PIT enforcement. Combine its slicing heuristics with Disclosed’s evidence gate.

## 3. Comparative matrix

| Project | India focus | Ingestion/data | PIT/versioning | Ratios/forensics | Valuation | Sector adaptation | NLP/citations | Scoring/output | License | Reusable lesson |
|---|---|---|---|---|---|---|---|---|---|---|
| Fundamental-Screener | Strong | NSE/BSE drops, filing CSV/XBRL, Screener | Raw hashes, date partitions, dissemination time; incomplete universe history | Limited | Limited | Minimal | Filing split/dedupe | HUNT event priority | BSD-3-Clause | Immutable bronze manifest and defensive source pacing |
| Ananke | Strong, BSE | BSE registry and XBRL | Filing/context dates; no as-of reader | Statement mapping | None | No | None | Tables only | No licence | Preserve raw XML/context; never discard namespace |
| Disclosed | Strong, NSE/BSE filings | Announcements and attachments | Store-first cursor, dissemination time, retries | No financial ratios | None | No | Exact-span claim verification, OCR refusal path | Eval metrics, no investment score | MIT with metadata conflict | LLM claims are untrusted until deterministic evidence passes |
| Bharat-equity-skills | Strong vocabulary | Caller supplied | Caller responsibility | Best canonical M/Z/F calculators and India flags | None | BFSI exclusion/spec | Markdown evidence only | Transparent scorecards | MIT | Pure formula functions with missing/NA, not neutral fills |
| magic-formula-pit | Strong | Exchange universe, Screener, price/share data | 60-day availability proxy, listing clipping, walk-forward | Optional quality overlay | Greenblatt EY/ROC | Financial exclusions | None | PIT rank plus turnover buffer | MIT | Pre-register formula/rank variants and reconstruct historical EV |
| AnalystCollective | Generic/global | User-supplied packages | Source tiers and freshness validation | Some quality checks | Strong DCF, reverse DCF, Monte Carlo, SOTP | Model routing | Research-package provenance | Values, sensitivities, buy/fair/rich bands | MIT | Bounded solver, no-solution state and uncertainty-linked MoS |
| screener-mcp | Strong | Screener, NSE announcements/reports | Content cache, not historical PIT | Screener ratios | No audited proprietary model | No | PDF cache plus Chroma | MCP research output | MIT | Small authenticated adapters; keep unofficial routes isolated |
| jugaad-data | Strong | NSE/RBI and some BSE | Persistent cache; no revision/as-of model | None | None | No | None | DataFrames | Custom non-OSI | Pooled sessions and endpoint discovery |
| promoter-watch | Strong, governance | BSE shareholding and deals | Latest-quarter only | Pledge/deal alerts | None | No | None | 15/30/50 pledge bands | No reusable licence established | Separate disclosure fact, risk tier and legal meaning |
| equity-research-india | Strong | Screener document links | No PIT guard | Qualitative checklist | None | Limited prompts | MD&A/concall slicing; manual OCR | Narrative | MIT | Source hierarchy plus prepared/Q&A separation |
| **Project Research Bot / eqr** | **Native** | **NSE archives/API, Screener cache, XBRL parser, event schemas** | **visible_from, revision tables, hashes and manifests; XBRL empty and basis may mix per line** | **Broad fundamentals, 29 flags catalogued, 27 with evaluator branches; Beneish proxy/incomplete and Piotroski 7/9** | **DCF, reverse DCF, bands, EV/EBITDA, P/FCF, EPV, P/B, DDM, MoS, ER band** | **Six profiles with BANK/NBFC swaps** | **Citation schema/rejection exists; no concall/sections and 0 dossiers** | **Six pillars, DCI, verdicts, versioned manifests; r1 base remains default** | **Private/internal; no OSS licence** | **Already the best integrated spine; populate, correct and validate rather than rebuild** |

## 4. Patterns to adopt

These are implementation contracts for extending the live system. “Official” below means an exchange, regulator or first-party product statement; “external heuristic” means logic observed in an audited repository; and “EQR policy” means a proposed internal rule that must be versioned and calibrated. None of the rate limits or risk bands labelled EQR policy is an exchange-published permission or legal threshold.

### 4.1 Governed ingestion and basis integrity

**Screener contract.** Screener’s official help page says that premium users can export screen results as CSV and explicitly says, “we don't provide APIs.” EQR must therefore treat each permitted export or user-authorized response as an immutable source artifact: cache the raw bytes before parsing, and record account/export mode, query or company key, source URL, retrieval time, declared/as-observed period, HTTP metadata, SHA-256, parser/schema version and terms/authorization note. A cache is for reproducibility and load reduction, not evidence of permission. The code and this report must not describe direct HTML access as an official API or imply permission to scrape; if authorization or product behavior is unclear, stop and require a compliant export/source.

**NSE adapter contract.** Isolate every observed route behind a small versioned adapter. Establish a session by warming the public host, retain the resulting cookies, send consistent browser-like `User-Agent`, `Accept`, `Accept-Language`, `Referer` and compression headers, and use a finite connect/read timeout. Apply a bounded attempt count with exponential backoff plus jitter. A 401/403 may trigger one cache/session refresh; a 429 must honor `Retry-After` when supplied and otherwise back off; repeated 403/429, an HTML challenge where JSON is expected, schema drift, or identity mismatch must fail closed. Do not silently switch endpoints. `/api/annual-reports?index=equities&symbol=...` and similar routes are observed, undocumented routes, not a stable NSE API contract.

**BSE XBRL registry and taxonomy contract.** Discover filings from a dated registry snapshot and retain the unmodified registry row and raw XML. For every fact preserve the qualified namespace, taxonomy URI and version, local tag, context ID, entity, duration/instant, dimensions, basis, unit and scaling/decimals; for every filing preserve issuer/security identity, period, filing and revision/dissemination times, source URL, retrieval time, raw hash, byte count, parser version and supersession relation. Parse `in-bse-fin`, `in-capmkt` and `in-capmkt-ent` through separately tested maps, never by silently stripping namespaces. The official BSE XBRL page confirms categories including financial results, annual reports, audit qualifications, RPT, SAST and PIT disclosures, but the audited page did **not** expose a public `in-bse-fin` taxonomy package; taxonomy details inferred from filed instances remain observed source details until an official package is located.

**Internal source governor.** Start conservatively as proposed EQR policy: one in-flight request per host, at least four seconds between Screener requests, and a randomized 0.5–3.0 second delay for BSE/NSE registry or attachment calls, with a low daily retry budget. These are internal defaults, not exchange-published limits. Centralize 429/403 handling, bounded exponential backoff with jitter, circuit breaking, session/cache refresh and manual re-enable. Write an append-only manifest before parse/load; object keys are content-addressed or source-and-time versioned, exact repeats are idempotent no-ops, revisions create new immutable rows, and no retry may overwrite prior bytes.

**Atomic basis selection.** Select consolidated (`C`) or standalone (`S`) once per issuer/period/statement after completeness and identity checks, then use only that basis for every line in the statement. Prefer consolidated only when its required-line coverage passes; otherwise choose a complete standalone statement and record the reason. If neither basis is complete, or a selected statement contains conflicting basis/context facts, quarantine the whole issuer-period-statement. Never fill individual missing consolidated lines from standalone data: mixed-basis periods are neither scored nor valued.

### 4.2 Canonical forensic calculators and missingness

For non-financial corporates, implement the named eight-index Beneish model exactly:

`-4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI + 4.679 TATA - 0.327 LVGI`.

- `DSRI = (receivables_t / sales_t) / (receivables_t-1 / sales_t-1)`.
- `GMI = gross_margin_t-1 / gross_margin_t`, where `gross_margin = (sales - COGS) / sales`.
- `AQI = [1 - (current_assets + net_PPE + marketable_securities)_t / total_assets_t] / [1 - (current_assets + net_PPE + marketable_securities)_t-1 / total_assets_t-1]`.
- `SGI = sales_t / sales_t-1`.
- `DEPI = [depreciation_t-1 / (depreciation_t-1 + net_PPE_t-1)] / [depreciation_t / (depreciation_t + net_PPE_t)]`.
- `SGAI = (SG&A_t / sales_t) / (SG&A_t-1 / sales_t-1)`.
- `TATA = (income_from_continuing_operations_t - CFO_t) / total_assets_t`; retain the precise accrual-definition version in the manifest if a fuller balance-sheet construction is used.
- `LVGI = [(current_liabilities + long_term_debt)_t / total_assets_t] / [(current_liabilities + long_term_debt)_t-1 / total_assets_t-1]`.

All eight named indices must be present, finite, same-basis, annual and comparable; denominators must be positive where the definition requires it. A missing input, non-comparable period, proxy substitution or failed basis/provenance check produces `UNKNOWN`, not a partial score and not a neutral fill. BANK and NBFC_FIN return `NA`. Keep the pre-registered EQR flag at `>-1.78` and review band `(-2.22, -1.78]`, but attach formula/threshold version and provenance: these are model screening bands, not findings of manipulation.

For non-financial corporates, implement the emerging-market Z-double-prime form exactly:

`Z″ = 3.25 + 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4`, with `X1=(current assets-current liabilities)/total assets`, `X2=retained earnings/total assets`, `X3=EBIT/total assets`, `X4=book equity/total liabilities`.

Require positive total assets and liabilities, consistent annual period/basis and non-proxy inputs; otherwise return `UNKNOWN`. BANK and NBFC_FIN return `NA`. Do not impose a universal distress cutoff: any operating bands must name the paper/model variant, sample, sector and calibrated EQR version.

Piotroski is nine independent binary signals, never an estimated score from a subset:

- **Profitability (4):** ROA is positive; CFO is positive; ROA improves year over year; and CFO exceeds net income (low accruals).
- **Leverage, liquidity and source of funds (3):** long-term leverage declines; current ratio improves; and no new equity is issued.
- **Operating efficiency (2):** gross margin improves; and asset turnover improves.

Each signal needs two comparable annual, PIT-visible periods where applicable. Unknown inputs make that signal unknown and suppress the total until the completeness policy is met; they do not score zero or one. Live `eqr` currently implements 7/9: current-ratio improvement and gross-margin improvement are the missing signals.

### 4.3 India red-flag register

This table deliberately separates regulatory triggers from triage policy. Depending on the cited rule and its current scope, exemptions and version, a regulatory threshold may trigger **disclosure, shareholder approval or an open offer**; the consequence is identified per row. None of those consequences by itself establishes risk, misconduct or a rating action. Every EQR/external band below must live in versioned configuration and be calibrated on PIT data before it can change a published score.

| Subject | Scope | Trigger | Severity | Regulatory/EQR consequence | Data needed | Provenance/status |
|---|---|---|---|---|---|---|
| CFO/PAT | Non-financial, trailing five annual years plus annual sequence | `<0.8` for two years = review; `<0.5` with receivables growing `>2x` revenue = severe | Review / severe | EQR watch/review only; no regulatory consequence asserted | PIT annual CFO, PAT, basis and filing versions | EQR/audited-repository triage heuristic; not law |
| CFO/EBITDA | Non-financial; project/seasonal exceptions documented | `<0.8` for two years = review; `<0.5` = severe | Review / severe | EQR watch/review only; no regulatory consequence asserted | CFO and consistently defined EBITDA/operating profit | Proposed EQR heuristic; uncalibrated, not law |
| Receivable days/growth | Non-financial, comparable annual periods | Receivable days `+20` over three years or receivable growth `>1.5x` revenue growth = review; `>2x` = severe | Watch / severe | EQR watch/review only; no regulatory consequence asserted | Revenue, trade receivables, days convention, acquisitions/basis | EQR plus audited-repository heuristic; sector-adjust before use |
| Inventory days/growth | Inventory-bearing non-financial issuers | Inventory days `+20` over three years or inventory growth `>1.5x` revenue growth = review; `>2x` = severe | Watch / severe | EQR watch/review only; no regulatory consequence asserted | Revenue/COGS, inventory, days convention, sector and period basis | Proposed EQR triage heuristic; not law |
| Other-income dependence | All non-financial issuers; read source notes | Other income/PBT `>=25%` = watch; `>50%` in two FYs = rating review/cap candidate | Watch / review | EQR watch/review only; no regulatory consequence asserted | Other income, PBT, recurring/non-recurring note classification | Existing EQR bands plus audited-repository heuristic; not law |
| Cash-tax gap/rate | Tax-paying non-financial issuers, three comparable FYs | Cash-versus-book tax-rate gap `>10 pp` for three FYs, or cash ETR `<60%` of applicable statutory rate, requires reconciliation | Watch / review | EQR watch/review only; no regulatory consequence asserted | Cash tax, PBT, tax expense, statutory rate, deferred-tax and holiday notes | Existing EQR gap plus audited-repository heuristic; not allegation of evasion |
| RPT/revenue | All issuers; denominator is annual consolidated revenue | EQR review at `>=5%`, severe review at `>=15%`; separately assess LODR Reg. 23's applicable material-RPT threshold: `₹1,000 crore` or `10%` of annual consolidated turnover, whichever is lower | Review / severe; legal workflow separate | Applicable material RPTs require prior shareholder approval, subject to the rule's current scope, exemptions and version | Audited RPT note, counterparty/control, terms, revenue and approval/disclosure filing | 5/15% are internal heuristics; [LODR Reg. 23](https://www.sebi.gov.in/legal/regulations/aug-2025/sebi-listing-obligations-and-disclosure-requirements-regulations-2015-last-amended-on-august-08-2025-_96661.html) is the material-RPT/shareholder-approval anchor and must be versioned |
| Contingent liabilities/equity | Non-financial; exclude ordinary-course items only with documented policy | `>=50%` = review; `>=100%` = severe; guarantees/litigation always require note review | Review / severe | EQR watch/review only; no regulatory consequence asserted | Audited contingencies, guarantees, litigation, book equity/net worth | EQR sensitivity heuristic; not a legal solvency threshold |
| Promoter pledge/encumbrance | Percentage of promoter/group holding, never silently percent of total capital | Any non-zero/recent rise = review; `>=10%` high, `>=20%` severe, `>=50%` critical; escalate a QoQ rise `>5 pp` | Review / high / severe / critical | Applicable SEBI encumbrance disclosure; EQR tiers add risk review only | Shareholding/encumbrance filings, both percentage denominators, event and revision times | Risk tiers are EQR policy; SEBI encumbrance filings are regulatory evidence, not these risk thresholds |
| Interest coverage | Non-financial, consistently defined EBIT/interest | `<1.5x` = review; `<1.0x` = severe; combine with leverage/Altman evidence rather than infer default | Review / severe | EQR watch/review only; no regulatory consequence asserted | EBIT, finance cost, capitalized interest and sector | EQR/audited-repository sensitivity bands; not law |
| CWIP/asset base | Asset-heavy non-financial issuers | CWIP/net block `>=20%` = review; `>=40%` = severe, subject to commissioning plan | Review / severe | EQR watch/review only; no regulatory consequence asserted | Audited CWIP, net block/PPE, age and project schedule | Audited-repository triage heuristic; proposed EQR policy |
| Auditor qualification/resignation | All issuers | Qualification, adverse opinion, disclaimer or resignation with reasons = hard forensic case; routine rotation alone does not fire | Hard review | Applicable exchange disclosure; EQR severity adds forensic review, not a fraud finding | Signed audit report, exchange filing, effective/event time, reasons and successor | Filing is regulatory evidence; severity is EQR policy, not proof of fraud |
| SAST events | All issuers and persons acting in concert | Reg. 3(1): acquisition taking the acquirer/PAC to `25%` or more voting rights; Reg. 3(2): for a holder already at `25%` or more but below maximum permissible non-public shareholding, acquisition of generally `>5%` additional voting rights in a financial year | Regulatory/legal review | The applicable Reg. 3 threshold triggers an open-offer obligation, subject to the regulation's current computation rules, exemptions and version; it is **not** a bearish heuristic or misconduct finding | SAST disclosure, pre/post holding, denominator, person/group, event and dissemination time | [SEBI SAST Regulations, Reg. 3](https://www.sebi.gov.in/legal/regulations/oct-2011/sebi-substantial-acquisition-of-shares-and-takeovers-regulations-2011-last-amended-on-december-17-2025-_34636.html), versioned independently from EQR policy |
| Insider events | Promoters, directors and designated persons | Preserve all trades; PIT Reg. 7(2) generally uses aggregate traded value `₹10 lakh` in a calendar quarter (company code may be lower); EQR separately reviews clustered sales or any new pledge | Disclosure review / EQR watch | Regulatory disclosure when applicable; EQR clustering/pledge review is separate and has no legal consequence | PIT filing ID, person/role, side, quantity/value, pre/post holding, quarter and dissemination time | Regulatory disclosure trigger plus separate EQR triage; verify current regulation/version before use |

### 4.4 Governed valuation outputs

`eqr/fundamentals/valuation.py` already computes reverse-DCF `implied_growth`; the extension is a solver contract, not a new feature claim. The request must explicitly name the one solved variable (for example initial revenue growth, terminal margin or cost of capital), hold all others in a versioned assumption object, and supply economically defensible lower/upper bounds. Evaluate both endpoints and test monotonicity on a coarse grid; bracket a root only when the signed price error changes sign and the objective is monotone over the selected interval. Then use bisection or a guarded Brent-style method with declared price/growth tolerance, iteration cap and deterministic stopping rule. If bounds do not bracket, monotonicity fails, a valuation is invalid, or the cap is reached, return `NO_SOLUTION` with endpoint values and reason—never a midpoint or neutral growth rate.

Persist and display the solved variable/value, current price, valuation target, bounds, endpoint errors, monotonicity/bracket results, tolerance, iterations, convergence status, horizon, WACC/terminal-growth path, margin/reinvestment path, net-debt/share bridge, data/as-of dates, assumption/model versions and source manifest. Publish downside/base/upside sensitivity scenarios, including coupled growth-margin and WACC-terminal-growth stresses.

Margin of safety is `MoS = (fair_value - price) / fair_value`; an invalid/non-positive fair value is unknown. As an evidenced v0 cross-check policy—not a primary valuation target—derive `base_required_MoS = clip(0.5 × (P90 - P10) / median, 15%, 50%)` from a valid fair-value distribution with a positive median. Then set `required_MoS = clip(base_required_MoS + p_completeness + p_cyclicality + p_disagreement, 15%, 50%)`, where every penalty is non-negative and supplied by versioned, calibrated policy. If the distribution or penalty inputs are invalid, or an applicable penalty lacks explicit configuration, return `UNKNOWN`; never silently zero-fill a penalty. Over a stated `H`-year horizon, compute annualized expected return for each terminal value as `(terminal_value / price)^(1/H) - 1`, including modeled dividends/cash distributions only when explicitly defined. Display **bear, mid/base and bull annualized returns**, horizon and terminal assumptions. Missing scenario inputs remain unknown; there is no silent neutral fill.

Graham value and EPV are transparent cross-checks only, not primary targets. Show formula, inputs, invalid-input guards and applicability; suppress Graham on negative earnings/book value and suppress or qualify EPV where normalized earnings cannot be defended. Retain sector routing: industrial DCF/comps may be primary for GENERAL/IT/PHARMA/CYCLICAL, while BANK and NBFC use justified P/B, residual-income/DDM and peer/regulatory-capital views rather than industrial FCF.

### 4.5 BFSI metric swaps

| Industrial metric | BANK replacement | NBFC replacement | Rationale |
|---|---|---|---|
| Revenue growth / EBITDA or OPM | NII growth, net interest margin, fee income and cost-to-income | AUM/disbursement growth, spread/NIM and cost-to-income | Interest, funding and credit costs are operating items for lenders |
| Receivable/inventory/CCC working capital | Deposit mix/CASA, liquidity coverage and maturity gaps | Borrowing mix, ALM buckets and liquidity buffer | Industrial working-capital cycles do not describe funding liquidity |
| Debt/equity, net-debt/EBITDA, Altman Z″ | CET1/CAR, leverage ratio and regulatory buffers | CAR/Tier 1, gearing and ALM | Deposits/borrowings are productive funding; industrial Altman is invalid |
| CFO/FCF conversion and industrial DCF | Capital generation, payout capacity and residual income/DDM | Capital generation, normalized credit-cost earnings and residual income/DDM | Cash-flow classification is structurally different and industrial FCF is misleading |
| Receivable quality / inventory ageing | GNPA, NNPA, slippages, PCR, write-offs and restructured book | Stage 2/3 assets, GNPA/NNPA, collection efficiency, PCR and write-offs | Loan-book migration and provisioning measure asset quality |
| Beneish/accrual quality | Provision coverage, credit-cost normalization, interest reversal and fee-quality checks | Stage migration, ECL overlays, collection/cash realization and securitization gains | Industrial Beneish components do not map cleanly to regulated lenders |
| EV/EBITDA, P/FCF, industrial DCF | P/B versus sustainable ROE/COE, residual income and DDM | P/B or P/AUM with normalized ROA/ROE, residual income and DDM | Equity capital, book quality and regulated solvency drive lender value |

Industrial Beneish, Altman, CFO/FCF conversion, working-capital and industrial-DCF metrics must return `NA`—not zero, “clean,” or a neutral score—for BANK and NBFC_FIN. Coverage/confidence must disclose the routed metric set.

## 5. Roadmap for the live eqr codebase

`eqr/fundamentals/forensic.py`, `eqr/fundamentals/valuation.py`, `eqr/rating/flags.py`, `eqr/rating/sector.py`, `eqr/spine/xbrl.py`, and `eqr/research/dossier.py` already exist. This roadmap extends or corrects those modules; it does not replace them.

Every ingestion and score artifact must carry an immutable manifest with source/data/parser/formula/config versions. Coverage is a denominator-backed state, not “no exception raised.” Missing, quarantined, stale or inapplicable input is `UNKNOWN`/`NA`, never zero. For every score-path change below, PIT-safe fixtures and invariant tests come first; no score-path change ships without a full walk-forward rerun and validation-diff review; r1 `base` remains the published default unless the registered promotion gates pass.

| Priority and file/action | Concrete scope/deliverable | Effort | Dependency / rollout order | Exact PIT and validation gate |
|---|---|---|---|---|
| 1. `[MODIFY] eqr/spine/xbrl.py` and existing `eqr xbrl --backfill-from` CLI | Add registry discovery and resumable FY2018-onward backfill; persist raw registry/XML, taxonomy/namespace/context/unit/basis, filing/revision time, raw URL/hash, parser version and supersession; reconcile consolidated/standalone identity and coverage. The CLI is existing, not `[NEW]`. | 3–5 weeks | Source-governor/terms review, registry adapter, storage migration and issuer map; blocks 2, 4–7 | For every eligible issuer-period since FY2018, registry outcome is downloaded, explicit unavailable or failed with reason; `>=95%` registry coverage, `>=98%` successful raw retrieval for discovered URLs and `>=95%` parse coverage before rollout. `100%` loaded filings have URL/hash/retrieval/filing time, taxonomy/parser version and basis; revision fixtures preserve both versions; as-of queries exclude later filings; zero cross-issuer/period identity mismatches and zero mixed-basis statements. |
| 2. `[MODIFY] eqr/store/pit.py` | Replace per-line consolidated preference with atomic issuer/period/statement basis selection; persist decision/completeness, quarantine conflicts and add invariant tests. | 1–2 weeks | XBRL basis metadata and completeness specification from 1; blocks forensic/valuation consumption | PIT fixtures prove `visible_from <= as_of`, later revisions cannot leak, and every returned statement has exactly one basis. Gate is zero line-level basis mixing across the full store, `100%` decision-manifest coverage, and explicit quarantine when neither basis passes required-line completeness. |
| 3. `[NEW] eqr/spine/pledges.py` | Ingest pledge/encumbrance, insider/PIT and SAST disclosures with event/dissemination/revision times, filing IDs, dedupe, person/group identity and explicit `% of promoter holding` versus `% of total capital` semantics. | 2–4 weeks | Source/terms review, issuer/person identity map and event schema; after 1–2, before flags | Reconcile each source-date page to an immutable manifest; `>=95%` expected source-date coverage and `100%` accepted events with source URL/hash, event time, dissemination time, denominator semantics and revision key. Replay is idempotent, revisions supersede rather than overwrite, and an event is invisible before dissemination time. A flag cannot fire for a denominator/date marked unknown. |
| 4. `[MODIFY] eqr/fundamentals/forensic.py` | Replace positional Beneish components with a named eight-index object sourced from XBRL; remove the coefficient-shift hazard; add prior-year M-score, Piotroski 9/9, real Altman inputs, RPT/contingent ratios and explicit BFSI `NA` routing. | 2–3 weeks | Atomic statements from 1–2; RPT/contingency facts; formula/config versioning | Golden fixtures match canonical formulas and prove no coefficient moves when a field is missing; each score fires only with all required named, finite, same-basis, PIT-visible periods (`8/8` Beneish, `9/9` Piotroski, `4/4` Altman) and never for BFSI. **PIT-safe fixtures/invariant tests first; full walk-forward rerun plus validation-diff review; r1 `base` remains published default until promotion gates pass.** |
| 5. `[MODIFY] eqr/rating/flags.py` | Add calibrated cash, working-capital, RPT, contingent, pledge/insider/SAST and auditor thresholds; distinguish disclosure facts from risk bands; make missing-data and sector behavior explicit; correct the three existing gaps (`REGULATORY_FRAUD` and `VALUATION_DISPERSION_GT_50` lack evaluator branches, while `FORENSIC_CASH_DIVERGENCE` omits its documented prior-year condition); and consume populated event/forensic evidence. | 2–3 weeks plus calibration | 3–4, event reconciliation and threshold registry; cannot precede population | Every flag fixture includes just-below/at/above boundaries, sector/NA and late-arriving revision cases; a signal fires only when its named evidence set is `OK`, in-scope, non-stale and above its family’s declared coverage floor (`>=95%` event-source reconciliation or complete required financial periods). **PIT-safe fixtures/invariant tests first; full walk-forward rerun plus validation-diff review; r1 `base` remains published default until promotion gates pass.** |
| 6. `[MODIFY] eqr/fundamentals/valuation.py` | Expose governed reverse-DCF variable/bounds/bracket/convergence diagnostics and publish bear/base/bull expected-return bands; add applicable Graham cross-check. Reverse DCF, expected-return calculation and EPV already exist. | 1–2 weeks | Atomic statements, share/net-debt integrity, assumption registry; UI/report exposure follows | Solver fixtures cover root at each bound, monotone interior root, no bracket, non-monotone and iteration-cap states; `100%` displayed valuations carry as-of/price/share/assumption versions and diagnostics, and all three ER scenarios or explicit unknowns. No scenario/price/share input may default. **PIT-safe fixtures/invariant tests first; full walk-forward rerun plus validation-diff review; r1 `base` remains published default until promotion gates pass.** |
| 7. `[MODIFY] eqr/features/fundamental.py` | Where needed, expose corrected forensic/valuation/event fields into features and score inputs; enforce split-invariance for per-share/share-count/market-cap features. `MCAP_NOT_SPLIT_INVARIANT` remains open. | 1–2 weeks | 2, 4–6 and corporate-action/share history | Split fixtures apply equivalent pre/post-split economics and require identical ranks/scores/valuation within numeric tolerance; every exposed field retains source metric/status/version and cannot coerce missing to zero. **PIT-safe fixtures/invariant tests first; full walk-forward rerun plus validation-diff review; r1 `base` remains published default until promotion gates pass.** |
| 8. `[NEW] eqr/research/concall.py` | Add Pydantic `SourceArtifact`, `EvidenceSpan` and claim models; retain document hash and page/span citations; verify numbers and periods; persist `VERIFIED`/`REFUSED`; separate prepared remarks/Q&A and guidance versus delivery. Feed only experimental r3 `with_qual`. | 3–5 weeks | Document acquisition/OCR/page mapping and source identity; independent of r1 rollout | `100%` VERIFIED claims resolve to the hashed bytes and page/span, every number/period matches local context, and mutated word/digit/period/speaker/page adversarial fixtures are refused (`0` false accepts). Report extraction coverage, acceptance/refusal and native/OCR split by parser version. Publication time must be `<= as_of`; unknown publication time is excluded. Hard test: no import/read path from r1 `base`. |
| 9. `[MODIFY] eqr/research/dossier.py` | Include source and canonical URLs, hashes, page/span, source/parser versions and evidence/refusal state in dossier packs; backfill existing artifacts and publish acceptance/refusal metrics. | 1–2 weeks | 8 plus document-store migration | `100%` accepted claims have artifact URL/hash/version and resolvable page/span; every rejected claim retains reason; backfill reports populated, unresolvable and refused denominators. PIT pack generation excludes artifacts published after `as_of`; serialization round trips without losing provenance. |
| 10. `[MODIFY] eqr/strategy/rank.py` | Add a Greenblatt/Magic-Formula PIT quality variant as a pre-registered experiment; reconstruct historical EV/share count, define EY/ROC inputs, invalid-value exclusions and turnover buffers. Never silently change production weights. | 2–4 weeks plus validation window | 1–2, 4, 7, corporate-action/share/debt/cash history and experiment registration | Signal is suppressed unless `>=90%` of the eligible universe-date has PIT-valid EBIT, debt, cash, share count/price and invested-capital inputs; no current market cap may backfill history. Turnover and availability invariants pass. **PIT-safe fixtures/invariant tests first; full walk-forward rerun plus validation-diff review; r1 `base` remains published default until the pre-registered risk/return, turnover, coverage and stability promotion gates pass.** |

### Phased execution and exit criteria

1. **Authoritative data (1–3):** exit only when FY2018-onward registry/filing/event denominators meet the stated coverage gates, every accepted artifact is hashed/versioned/PIT-timed, replay is idempotent, revisions survive and the mixed-basis invariant is zero.
2. **Deterministic calculations (4–7):** exit only when canonical golden fixtures and NA/missing/basis/split invariants pass, each firing signal meets its completeness gate, `MCAP_NOT_SPLIT_INVARIANT` is closed or the affected feature remains disabled, and a full walk-forward plus validation-diff review approves an explicitly versioned candidate. Published r1 `base` is unchanged until promotion.
3. **Verified qualitative evidence (8–9):** exit only when adversarial claim tests have zero false accepts, every VERIFIED claim resolves to URL/hash/page/span, refusal and coverage metrics are published, PIT filtering passes, and the route remains isolated to experimental r3 `with_qual`.
4. **Experimental ranking (10):** exit only when historical EV/share reconstruction meets `>=90%` universe-date coverage, turnover and PIT invariants pass, and the pre-registered walk-forward gates beat the declared benchmark without an unreviewed production-weight change.
