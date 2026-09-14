# Research Bot — Codex Research-Quality Improvement Plan

> **For agentic workers:** This is a master roadmap spanning several independently testable subsystems. Before implementation, split each numbered phase into its own execution plan and use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement it task by task. Do not run multiple tasks against the same DuckDB file concurrently.

**Goal:** Turn `eqr` from a promising point-in-time research prototype into a reproducible, audit-ready research system whose quantitative results and LLM dossiers can be trusted, challenged, and regenerated.

**Architecture:** Preserve the existing layered design, but place immutable source artifacts, temporal identity, data manifests, experiment registration, and evidence verification at every boundary. Deterministic data and rating engines remain authoritative; LLM output is a cited, verified interpretation layer and never changes a rank or reaches an order path.

**Tech stack:** Python 3.13, DuckDB, pandas/NumPy/SciPy, Typer, FastAPI/Jinja2, pytest, pypdf/pdfplumber, NSE/BSE primary-source data, Screener as a secondary source, and Claude through a versioned adapter.

**Review inputs:** `README.md`; `docs/REBUILD_SPEC.md`; `docs/DATA_SOURCES.md`; `docs/VALIDATION.md`; `docs/superpowers/specs/2026-09-14-research-bot-design.md`; `docs/superpowers/plans/2026-09-14-fundamentals-x10-plan.md`; `Research bot, improvement plan by Genie One.md`; all tracked `eqr/`, `tests/`, `deploy/`, and web-template files; the local DuckDB metadata and stored validation reports.

## Global constraints

- Point-in-time means the fact was genuinely available at the decision timestamp. A value first fetched in 2026 and assigned a 2019 filing date remains **as-restated historical data** unless an immutable 2019 artifact proves the original value.
- Every derived row must identify its source artifacts, visibility timestamp, transform version, and input manifest hash.
- `UNKNOWN`, `NOT_APPLICABLE`, `SOURCE_CONFLICT`, and `DATA_ERROR` are distinct states. None may be silently converted to zero.
- LLM text never changes sleeve scores, target weights, hard gates, or the deterministic rating. Qualitative inputs remain capped and independently calibrated.
- A strategy or rating version cannot be called validated after its holdout has been inspected, after an input defect is found, or after its data/logic changes. It must receive a new version and a new test protocol.
- Sleeve S remains diagnostic. Sleeve L should be labelled `PROVISIONAL_REVALIDATION_REQUIRED` until the Phase 1 and Phase 2 gates in this plan pass.
- Raw artifacts remain immutable and gitignored. Secrets remain outside prompts, reports, logs, and version control.
- The existing Fundamentals ×10 plan remains the feature-expansion design. Where sequencing conflicts, this plan's integrity gates run first.

---

## 1. Executive assessment

### 1.1 Overall verdict

The project has an unusually good foundation for a young personal research system: explicit layering, a large raw-data archive, point-in-time reader functions, next-session execution, transaction costs, walk-forward selection, an acceptance bar, and tests around core numerical paths. The documentation is candid about several limitations.

It is not yet safe to describe Sleeve L as fully validated or the dossiers as evidence-grounded in production. The strongest current label supported by the audit is:

- **Sleeve L:** promising historical result, provisionally accepted by the current protocol, but requires revalidation after temporal-data and experiment-governance defects are corrected.
- **Sleeve S:** not validated; keep disabled outside diagnostics.
- **Dossier system:** prototype only. It has zero stored production dossiers, single-symbol document coverage, syntactic rather than evidentiary citation checks, and historical pack leakage.
- **Fundamentals ×10:** strong approved design, but implementation is at the schema/XBRL-URL stage. Empty tables must not be confused with implemented capabilities.

### 1.2 What is already strong

- `eqr` is split into data spine, store, features, strategy, validation, research, and surfaces rather than one opaque pipeline.
- Raw NSE and Screener artifacts are cached; the store contains 5.45 million daily price rows and 2,735 trading sessions from 2016-01-01 through 2026-09-11.
- Signals are formed at a close and traded at the next open in `eqr/validate/backtest.py`.
- Missing numerical inputs generally remain `NaN` instead of being zero-filled.
- The simulator includes explicit charges, impact, position caps, industry caps, delisting haircuts, and daily mark-to-market.
- The current walk-forward code selects a configuration on expanding training windows, stitches out-of-sample folds, reports a holdout, and evaluates a written acceptance bar.
- The suite has 65 passing tests. Core feature, strategy, and backtest modules have strong line coverage.
- The Fundamentals ×10 plan already contains good target designs for XBRL, deterministic metrics, sector variants, rating manifests, verified quotes, calibration, and an append-only rating ledger.

### 1.3 Audit snapshot and material evidence

Review snapshot: 2026-09-14, repository `main` at `20b73ea`, three commits ahead of `origin/main`. The T1.2 commit and its follow-up correction landed during the review and complete Fundamentals ×10 task T1.2 (XBRL URL capture); both were inspected and preserved. T1.1 and T1.2 are therefore the only completed parts of that broader roadmap at this snapshot.

| Evidence | Observed state | Research implication |
|---|---:|---|
| Tracked project size | 117 files; about 17,092 tracked lines | Small enough for rigorous end-to-end controls now |
| Automated tests | 65 passed | Good baseline, but not proof of data validity |
| Total line coverage | 67% | Critical ingestion/quality paths are under-tested |
| Coverage examples | `quality.py` 0%, `refresh.py` 0%, `docstore.py` 23%, `http.py` 30%, `nse_api.py` 44% | Failures can enter upstream of well-tested calculations |
| Statements | 1,018,907 rows, 2,292 symbols | Broad secondary-source history |
| Statement observation time | Every statement row was first fetched on 2026-09-14; all have `fetched_at > visible_from` | Historical values are largely backdated/as-restated, not proven as-reported PIT values |
| Statement revisions | 0 | Revision logic is unexercised on real data |
| Historical control snapshots | `instruments`, `etf_list`, `surveillance`, and `fo_ban` each contain one distinct `as_of` date | Historical backtests do not actually reproduce those controls through time |
| Features | 98,186 rows over 117 dates | Useful research panel |
| Fully known four-bucket features | 85.5% overall; about 69.5% in 2017 and 96.3% in 2026 | Missingness is time-varying and can alter ranks |
| Corporate-action exposure | 13,266 feature rows across 362 symbols precede later split/bonus/consolidation factors | Current face value plus historical raw close can distort historical market cap and valuation |
| Quality checks | 11 checks, all for one date | Current green health does not certify the historical sample |
| Documents/dossiers | 14 documents for one symbol; 0 dossiers | Research-layer quality is not yet demonstrated across the universe |
| Validation history | Multiple same-day Sleeve L reports with changing results; the stated holdout was inspected repeatedly during repairs | The 2025-09 to 2026-09 period is no longer a pristine holdout |
| Cost specification | Code uses `10 + 50*sqrt(participation)` bps; design and validation docs state `10 + 25*sqrt(participation)` | Reported results are not tied to one unambiguous protocol |
| Risk-free configuration | `.env` exposes `EQR_RISK_FREE_PCT`, but validation uses a hard-coded 6% default | Configuration provenance is incomplete |

### 1.4 Highest-priority findings

#### P0 — validation blockers

1. **As-restated and survivorship-biased fundamentals.** `visible_from` is backfilled from filing dates, but the historical values were observed only in 2026. Delisted/renamed issuers are missing disproportionately. This directly affects Sleeve L's eligibility and value/quality ranks.
2. **Historical valuation is not split-invariant.** `features/fundamental.py` calculates shares using the current `instruments.face_value`, while `features/price.py` passes the historical raw close into market-cap calculations. The resulting mix is wrong for pre-action dates unless temporal face value is available.
3. **The holdout and trial count are not defensible after iterative repairs.** The same holdout appears in several reports. `n_trials = len(grid)` ignores earlier feature choices, reruns, bug fixes, and exploratory variants.
4. **Historical exclusion state is absent.** The strategy claims PIT ASM/GSM/F&O controls, but the local database has only a current snapshot. Early backtests therefore run without these filters.
5. **Protocol drift exists.** Impact coefficients differ between code and docs, the risk-free environment setting is unused, and the NIFTY 500 total-return benchmark is a price index plus a fixed 1.3% yield rather than an official TRI series.

#### P1 — research-output blockers

6. **Dossier citations are syntactic, not evidentiary.** `research/schema.py` accepts any whitelisted table name and any allowed document ID; it does not prove that the cited source supports the claim or number.
7. **Historical pack leakage.** `research/pack.py` does not filter `results_calendar` by filing time and reads the current `screener_meta` and current instrument row for historical packs.
8. **The response is not bound to the request.** `run_dossier` does not enforce that the returned `symbol` and `as_of` equal the requested values. The thesis itself has no citation field.
9. **Audit history can be overwritten.** `dossiers` is keyed only by `(symbol, as_of)` and written with `INSERT OR REPLACE`; `dossier_claims` is not keyed by `run_id`; `fund_metrics` omits `engine_version` from its primary key.
10. **Document retrieval is shallow.** The pack includes leading text excerpts rather than claim-addressable sections and tables. Page citations are allowed without checking that the page was supplied.

#### P2 — robustness and operational debt

11. **Missingness can improve apparent scores.** Bucket weights are renormalised over known data; partial Piotroski scores are not divided by `f_known`; two known buckets are sufficient. Coverage needs to affect confidence and eligibility explicitly.
12. **Source ingestion and quality gates lack test depth.** A 60% aggregate CI threshold, as suggested by Genie One, would pass while the highest-risk modules remain largely uncovered.
13. **Backtests do not currently refuse unresolved quality failures.** The quality table also lacks resolution/waiver state and data-slice manifests, so a simple count of all historical failures would be too crude.
14. **Entity continuity is symbol-based.** Symbol changes, reused tickers, mergers, demergers, and ISIN transitions need temporal identity rather than assuming one symbol is one permanent issuer.

---

## 2. Review of Genie One's plan

Genie One correctly prioritises survivorship, backtest quality gating, CI, dependency locking, and deferring Sleeve S. Its plan is useful but incomplete and contains two stale or incorrect recommendations.

| Genie item | Codex decision | Required change |
|---|---|---|
| Close survivorship gap | Keep and expand | Add issuer identity, as-reported artifact provenance, rename/delist coverage, missing-not-at-random analysis, and coverage gates; 2–3 days is optimistic |
| Panel adjustment materiality | Replace | Run a reproducible A/B pipeline; test raw close/temporal face value versus adjusted close/current-share units and re-rank every rebalance date |
| Add `statements_as_of` PIT test | Already present | `tests/test_store.py::test_statements_as_of_respects_visibility_and_basis` already covers the boundary; add real-artifact/revision and mixed-basis tests instead |
| Add CI | Keep, strengthen | Gate critical packages individually, run migration/reproducibility/no-network tests, and install from a lock file |
| Constant-time bearer comparison | Keep, low priority | Apply before exposing the API beyond localhost |
| Configure Telegram | Keep as operations work | Alert on stale/failed research dependencies, not merely job completion |
| Backtest quality gate | Keep, redesign | Gate on unresolved failures relevant to the exact manifest, with explicit waiver metadata and `--force` audit logging |
| Remove unused `yfinance` | Keep | Remove it unless a documented source adapter and provenance contract are added |
| Pin dependencies | Keep | Use a hashable lock plus numerical golden tests across supported platforms |
| Add `visible_from` to `instruments` | Replace | A single symbol-keyed row still overwrites history; build temporal instrument and identity tables |
| Sanitize `md_render` | Drop as stated | `eqr/surfaces/md.py::_inline` already calls `html.escape`; retain regression tests for hostile Markdown rather than adding an unnecessary sanitizer |
| Restrict `.env` permissions | Keep | Add `chmod 600`/owner validation to both installers |
| Add Ruff | Keep, low priority | Run after integrity work; linting does not repair research claims |
| Sleeve S redesign | Keep | Only after the corrected research harness is frozen and a new hypothesis is registered |
| Advisor hardening/VM | Keep deferred | Neither improves research validity today |

---

## 3. Target research architecture

```text
Immutable source artifact + SHA + observed_at
                    |
                    v
Temporal issuer identity ----> PIT curated facts ----> quality/coverage gate
                    |                    |                         |
                    |                    v                         |
                    +----------> versioned feature snapshot <-----+
                                         |
                         +---------------+---------------+
                         |                               |
                         v                               v
              deterministic rating              portfolio signal
                         |                               |
                         +----------> experiment registry
                                             |
                                             v
                             sealed validation + diagnostics

PIT facts + parsed sections + rating manifest
                    |
                    v
          evidence-addressable research pack
                    |
                    v
        LLM synthesis -> deterministic verifier
                    |
                    v
       append-only dossier + claim-level audit trail
```

Every published output must carry five identities: `data_manifest_sha`, `code_commit`, `engine_version`, `prompt_version` when an LLM is used, and `experiment_id` or `research_run_id`.

---

## 4. File and interface map

### New focused modules

| File | Responsibility |
|---|---|
| `eqr/audit/manifest.py` | Hash raw artifacts, table slices, settings, code commit, and environment into one immutable data manifest |
| `eqr/audit/claims.py` | Central state machine for `DIAGNOSTIC`, `PROVISIONAL`, `BACKTEST_PASS`, and `PROSPECTIVE_VALIDATED` |
| `eqr/store/identity.py` | Temporal issuer/symbol/ISIN mapping and rename/merger/delist resolution |
| `eqr/store/returns.py` | Corporate-action-aware security and benchmark total returns |
| `eqr/store/quality_gate.py` | Resolve applicable failures/waivers for a manifest and command |
| `eqr/validate/registry.py` | Immutable experiment specification, trial ledger, seal, and result attachment |
| `eqr/validate/diagnostics.py` | IC, quantiles, coverage, missingness, concentration, turnover, subperiod, and exposure diagnostics |
| `eqr/validate/statistics.py` | Block bootstrap, multiple-testing accounting, confidence intervals, and sensitivity comparisons |
| `eqr/research/evidence.py` | Typed claim evidence references for document quotes, table cells, calculations, and web artifacts |
| `eqr/research/verify.py` | Deterministic quote, numeric, temporal, symbol, and citation verification |
| `eqr/research/eval.py` | Frozen dossier evaluation set and metric runner |

### Existing modules requiring targeted changes

- `eqr/store/schema.sql`, `migrations.sql`, and `db.py`: temporal identity, manifests, experiments, append-only run keys, and migration invariants.
- `eqr/spine/refresh.py`, `nse_api.py`, `screener.py`, `adjust.py`, and `quality.py`: artifact provenance, historical control data, revision lanes, and coverage checks.
- `eqr/features/panel.py`, `price.py`, `fundamental.py`, `xsection.py`, and `build.py`: split-invariant valuation, explicit coverage, basis continuity, and manifest/version columns.
- `eqr/validate/backtest.py`, `walkforward.py`, `costs.py`, `metrics.py`, `acceptance.py`, and `report.py`: quality gates, official benchmarks, trial accounting, corrected holdout policy, and uncertainty intervals.
- `eqr/research/pack.py`, `schema.json`, `schema.py`, `dossier.py`, `docstore.py`: strict temporal reads, evidence atoms, deterministic verification, append-only storage, and evaluation metadata.
- `eqr/surfaces/queries.py`, templates, advisor response, and digest: honest claim state, data cut, coverage, staleness, and reason codes.

### Core target interfaces

```python
@dataclass(frozen=True)
class ArtifactRef:
    source: str
    path: str
    sha256: str
    published_at: datetime | None
    observed_at: datetime

@dataclass(frozen=True)
class TableSliceRef:
    table: str
    predicate: str
    row_count: int
    content_sha256: str

@dataclass(frozen=True)
class DataManifest:
    manifest_sha: str
    as_of: datetime
    code_commit: str
    schema_version: str
    settings_sha: str
    source_artifacts: tuple[ArtifactRef, ...]
    table_slices: tuple[TableSliceRef, ...]

@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    hypothesis: str
    engine_version: str
    data_manifest_sha: str
    train_range: tuple[date, date]
    validation_ranges: tuple[tuple[date, date], ...]
    sealed_holdout_range: tuple[date, date] | None
    variants: tuple[str, ...]
    acceptance_sha: str

@dataclass(frozen=True)
class ResearchPack:
    symbol: str
    security_id: str
    as_of: datetime
    manifest_sha: str
    tables: Mapping[str, tuple[Mapping[str, object], ...]]
    sections: tuple[Mapping[str, object], ...]

@dataclass(frozen=True)
class VerificationReport:
    publishable: bool
    supported: int
    struck: int
    reasons: tuple[str, ...]

def build_pack(con, symbol: str, as_of: date, manifest_sha: str) -> ResearchPack: ...
def verify_claims(dossier: Mapping[str, object], pack: ResearchPack) -> VerificationReport: ...
def assert_quality(con, manifest_sha: str, purpose: str, force: bool = False) -> None: ...
```

---

## 5. Phased implementation roadmap

## Phase 0 — Freeze claims and establish a reproducible baseline

**Duration:** 2–3 days  
**Purpose:** Stop ambiguous labels and make every later comparison attributable.

### Task 0.1 — Introduce honest claim states

**Files:** `eqr/audit/claims.py`, `eqr/surfaces/queries.py`, advisor response, templates, `README.md`, `docs/VALIDATION.md`

**Actions:**

1. Define the ordered states `DIAGNOSTIC`, `PROVISIONAL`, `BACKTEST_PASS`, and `PROSPECTIVE_VALIDATED`.
2. Map current Sleeve S to `DIAGNOSTIC` and Sleeve L to `PROVISIONAL`.
3. Make every dashboard, digest, report, and advisor payload display the state plus reason codes.
4. Reject a transition to `BACKTEST_PASS` while any P0 item in this plan remains open.
5. Reserve `PROSPECTIVE_VALIDATED` for at least 12 sealed forward months with no logic or data-definition changes.

**Tests:** status transition table tests; surface tests proving the word `VALIDATED` cannot be emitted from a bare historical `backtests.verdict` row.

### Task 0.2 — Add data and experiment manifests

**Files:** new `eqr/audit/manifest.py`, new manifest tables in `schema.sql`, `eqr/cli.py`, `tests/test_manifest.py`

**Actions:** hash sorted artifact SHAs, relevant table-slice counts/min/max dates, package lock hash, configuration, engine version, and Git commit. Add `eqr audit snapshot --as-of YYYY-MM-DD`. Store manifests append-only and reference them from feature, backtest, rating, and research runs.

**Tests:** same inputs produce the same hash; one byte, setting, table row, or code-commit change produces a different hash; ordering does not affect the hash.

### Task 0.3 — Capture the current result as a non-authoritative baseline

Create a baseline manifest for the current database and archive the existing reports with checksums. Record the observed 28.7% OOS CAGR, 1.28 Sharpe, 0.72 IR, and the Sleeve S failure as comparison points only. Do not overwrite or delete earlier reports.

**Phase 0 exit gate:** all surfaces show the revised claim state; every new run requires a manifest; baseline reports are immutable and checksum-addressable.

## Phase 1 — Repair point-in-time data and entity identity

**Duration:** 2–4 weeks, dominated by backfill and issuer matching  
**Purpose:** Ensure a historical decision sees only the identity and facts genuinely available then.

### Task 1.1 — Build a temporal security master

**Files:** `schema.sql`, new `eqr/store/identity.py`, `spine/refresh.py`, `universe.py`, `features/build.py`, tests with rename/relist/demerger fixtures

Create tables keyed by issuer/security and validity interval, not one mutable symbol row. At minimum store issuer ID, security ID, ISIN, symbol, series, name, listing/delisting dates, face value, sector/industry taxonomy and source, `valid_from`, `valid_to`, `observed_at`, and `visible_from`. Add explicit alias and corporate-event mappings.

`instrument_as_of(symbol, date)` must return exactly one security or a named ambiguity. A symbol reuse must never splice two issuers into one price series. Industry groups used in historical z-scores must come from the contemporaneous taxonomy snapshot.

**Done when:** time-travel tests cover a rename, face-value change, series migration, merger, demerger, delisting, and ticker reuse; no historical reader queries the current `instruments` row.

### Task 1.2 — Separate as-reported, as-restated, and observed facts

**Files:** `spine/screener.py`, planned `spine/xbrl.py`, PIT readers, statement schema, `tests/test_statement_provenance.py`

1. Store `source_artifact_sha`, `source_published_at`, `observed_at`, `revision_id`, `restated_flag`, and `truth_lane` on statement facts.
2. Use archived NSE/BSE XBRL or filed PDFs as the authoritative as-reported lane from 2018 onward.
3. Keep Screener history in an explicitly labelled `AS_RESTATED_SECONDARY` lane.
4. Before 2018, either obtain period-authentic filings or exclude the fundamental factor from the primary PIT claim. Never silently promote present-day history to as-reported.
5. Require basis continuity for growth calculations: do not mix consolidated and standalone periods inside one TTM/CAGR chain without an explicit bridge.

**Done when:** every historical feature can show whether it is as-reported or as-restated; a revised filing produces two immutable revisions; the primary validation lane contains no fact first observed after its claimed decision date without an authenticated period artifact.

### Task 1.3 — Close and measure survivorship/rename coverage

Use filing-feed symbols, ISIN, BSE code, historical exchange lists, and corporate-event mappings to resolve delisted and renamed names. Report coverage for every rebalance by name count, free-float/traded-value weight, sector, listing age, outcome type, and eventual return. Distinguish missing because the issuer failed from missing because parsing failed.

Run three comparisons:

- complete as-reported universe;
- observed-only universe with explicit coverage;
- adverse sensitivity in which missing names receive conservative quality/value ranks.

**Acceptance:** primary results require at least 95% eligible-name coverage and 98% traded-value coverage per fold, or a documented narrower start date. No sector may fall below 90% name coverage. If those bars cannot be met, publish results only for the supported cohort.

### Task 1.4 — Make market cap and valuation split-invariant

**Files:** `features/price.py`, `features/fundamental.py`, `features/panel.py`, temporal identity reader, `tests/test_valuation_actions.py`

Compute market cap from either contemporaneous raw close × contemporaneous shares or split-adjusted close × shares on the matching adjusted-share basis. Never mix current face value with historical raw close. Prefer directly filed weighted shares/outstanding shares; use equity capital/face value only with matching effective dates.

Build a deterministic counterfactual command that recreates every feature/rank date using the old and corrected methods and writes rank correlations, changed holdings, CAGR, Sharpe, IR, turnover, and per-symbol deltas. Include all 13,266 currently affected feature rows.

**Acceptance:** pre/post split market cap continuity is within 2% absent genuine issuance; unexplained valuation discontinuities are zero; all published Sleeve L results use the corrected lane.

### Task 1.5 — Reconstruct or remove historical controls

Backfill ASM/GSM/ESM, F&O-ban, ETF classification, and industry snapshots where reliable archives exist. For periods without trustworthy history, remove that filter from both strategy and benchmarked comparison rather than pretending current data existed in the past. Report both controlled-period and full-period sensitivities.

**Acceptance:** every exclusion at a rebalance has an artifact and visibility timestamp; a missing historical feed becomes `UNKNOWN_COVERAGE`, not an empty set.

### Task 1.6 — Turn quality checks into enforceable, resolvable gates

**Files:** `spine/quality.py`, new `store/quality_gate.py`, `validate/backtest.py`, rating/research orchestrators, CLI tests

Add severity, affected date/table/symbol, manifest hash, first seen, resolved time, resolver, waiver reason, and waiver expiry. A run must refuse unresolved `BLOCKER` failures relevant to its input manifest. `--force` requires a reason and records a non-validatable result state.

Add checks for source coverage, temporal leakage, duplicate business keys, artifact/hash mismatch, statement-basis switches, revision spikes, corporate-action reconciliation, stale classifications, price/index gaps, document extraction quality, and cross-source numerical agreement.

**Phase 1 exit gate:** a time-travel audit samples at least 100 symbols × 24 dates with zero unexplained future facts; temporal identity is unambiguous; coverage bars pass or the validation start date is narrowed; valuation counterfactuals are complete; blockers stop downstream runs.

## Phase 2 — Rebuild validation and statistical governance

**Duration:** 2–3 weeks after Phase 1  
**Purpose:** Make performance claims reproducible and resistant to data snooping.

### Task 2.1 — Freeze one authoritative return and benchmark model

**Files:** new `store/returns.py`, `validate/backtest.py`, `costs.py`, `metrics.py`, docs and golden tests

- Ingest official NIFTY 500 TRI if licensing/availability permits; otherwise label the proxy prominently and run yield sensitivities.
- Credit actual dividends and handle splits, bonuses, rights, mergers, demergers, tender offers, symbol changes, and cash distributions consistently for securities and benchmarks.
- Use a dated risk-free series or a versioned fixed assumption from the experiment spec; remove the unused environment/code split.
- Reconcile the impact coefficient. Use one value in code, docs, stored parameters, and reports.
- Distinguish delisting, temporary suspension, missing print, merger consideration, and bankruptcy. Five missing sessions alone is not sufficient evidence of delisting.

**Golden tests:** hand-worked split, bonus, dividend, rights, merger, suspension, and terminal-delist portfolios reconcile to the rupee.

### Task 2.2 — Make experiments immutable and count all trials

**Files:** new `validate/registry.py`, experiment tables, CLI/report changes

Register hypothesis, data manifest, source lane, feature version, grid, cost model, benchmark, folds, purge/embargo, acceptance bar, and holdout before execution. Seal the record with a hash. Every exploratory run and material data/logic repair increments the research-trial ledger. A result whose sealed spec changes is invalid rather than updated in place.

The current 2025-09 to 2026-09 holdout becomes a **development evaluation period**, not an untouched holdout. Reserve a new prospective window beginning after the corrected engine is frozen. Until it matures, use nested historical validation and the `BACKTEST_PASS` label.

### Task 2.3 — Use nested, leakage-aware validation

For each outer fold, fit winsorisation choices, transforms, feature inclusion, thresholds, and variant selection only on the training portion. Purge at least the maximum feature/holding overlap and embargo the intended forecast horizon. Preserve date order; never use random row splits.

Report bootstrap confidence intervals for CAGR, Sharpe, IR, drawdown, turnover, and alpha; probability of underperforming the benchmark; Deflated Sharpe using the complete trial ledger; and a multiple-testing correction or reality-check statistic across searched variants.

### Task 2.4 — Add factor and portfolio diagnostics

**Files:** new `validate/diagnostics.py`, `statistics.py`, report templates, planted-signal tests

At every fold and full period report:

- rank IC and Pearson IC with confidence intervals;
- quantile monotonicity and long-short spread;
- coverage, missingness, and rank conditional on coverage;
- feature correlation, marginal contribution, and ablation;
- sector, size, beta, volatility, liquidity, and momentum exposures;
- holdings overlap, concentration, turnover attribution, crowding/capacity;
- subperiod, bull/bear, drawdown, and stress performance;
- sensitivity to costs, execution delay, slippage, price limits, missing data, and delisting recovery;
- contribution by year and symbol so 2021/2023 dependence is visible.

Normalize partial Piotroski as `f_score / f_known` or require a fixed known-component threshold. Do not let low-coverage names receive a free score through weight renormalisation; separate score from confidence and eligibility.

### Task 2.5 — Revalidate Sleeve L; keep Sleeve S quarantined

Run, in order, one-variable counterfactuals for each repaired defect, then the combined corrected engine. Attribute the change in CAGR/Sharpe/IR to statements, identity, valuation, exclusions, returns, benchmark, and costs.

**Downgrade rule:** any single plausible correction changing CAGR by more than 2 percentage points, Sharpe by more than 0.10, IR by more than 0.10, or more than 20% of holdings requires explicit root-cause analysis and a new engine version.

**Backtest-pass bar:** retain the existing minimums only after all integrity gates pass, and add positive median fold excess, no single year contributing more than 40% of total excess wealth, stable sign across cost/coverage sensitivities, and confidence intervals that do not make the headline misleading.

Do not redesign Sleeve S in this phase. First lock the repaired harness; then register one economically motivated low-turnover experiment with a fixed search budget.

**Phase 2 exit gate:** one sealed experiment reproduces from raw artifacts to report on a clean database; all trial IDs are enumerated; no period is described as untouched after inspection; Sleeve L is either `BACKTEST_PASS` with caveats or honestly remains `PROVISIONAL`.

## Phase 3 — Implement deterministic fundamentals and ratings on the repaired spine

**Duration:** 3–5 weeks; reuse the Fundamentals ×10 plan  
**Purpose:** Expand analytical depth without weakening provenance.

### Task 3.1 — Correct schema versioning before filling new tables

Amend the recently added schema before loaders create durable history:

- include `engine_version` in the `fund_metrics` key;
- key dossiers by immutable `run_id` and retain all accepted/rejected attempts;
- key `dossier_claims` by `run_id, claim_id`;
- link ratings/calibrations to manifest and experiment IDs;
- store prompt/model/parser versions and source artifact hashes;
- make revision/audit tables append-only;
- ensure graph facts can be reconstructed as of both valid time and observed time.

Migration tests must exercise a pre-v2 database, repeated migration, rollback from backup, and constraint preservation.

### Task 3.2 — Execute the existing XBRL and filings plan with provenance gates

Continue Fundamentals ×10 tasks T1.2–T1.6, but require raw SHA, exact filing/broadcast time, taxonomy version, units, scale, parser version, and revision identity on every load. Validate XBRL totals against filed PDFs and Screener; a disagreement remains a conflict and never silently chooses the convenient number.

### Task 3.3 — Build sector-aware metrics and explicit confidence

Execute the planned forensic, quality, valuation, governance, and sector KPI modules. Keep financials, utilities, commodity businesses, and non-financials on appropriate metric sets. Each metric returns value/status/unit/provenance/inputs-as-of. Compute score and confidence separately; make missingness and source disagreement visible.

### Task 3.4 — Calibrate each engine version independently

The rating calibration in the Fundamentals ×10 plan must use the repaired data manifest and experiment registry. r1, r2, and later versions are separate hypotheses, not revisions of one result. Validate monotonicity, IC, long-short spread, transition rate, Brier score, calibration slope/intercept, coverage, and stability by sector/size/year.

**Phase 3 exit gate:** a rating is deterministic from its manifest; all gates and missing inputs are explainable; a clean rebuild reproduces every rating; uncalibrated engines are visibly diagnostic.

## Phase 4 — Make dossiers evidence-grounded and measurable

**Duration:** 2–4 weeks after the deterministic data contract stabilises  
**Purpose:** Ensure every published narrative claim is traceable to supplied evidence.

### Task 4.1 — Fix the research-pack temporal contract

**Files:** `research/pack.py`, PIT readers, `tests/test_pack_pit.py`

Centralize all pack reads in typed as-of readers. Filter results by `filing_dt <= as_of`; never use current Screener meta or current instrument classifications for a historical pack; include table names that exactly match citation names. Bind the pack to one symbol, security ID, as-of timestamp, manifest, and engine rating.

Add poison-row tests: insert future filings, future classifications, future news, revised statements, unrelated symbols, and documents published one second after the cutoff; none may appear.

### Task 4.2 — Replace generic citations with evidence atoms

Every claim must carry one or more typed references:

```python
@dataclass(frozen=True)
class TableCellEvidence:
    table: str
    row_key: Mapping[str, str | int | float]
    field: str
    value: str | int | float
    unit: str
    visible_from: datetime
    artifact_sha: str
```

Document claims require an exact or normalized quote, document/section/page ID, artifact SHA, and publication time. Calculated claims require formula, inputs, units, and tolerances. Web claims require an archived source, published/fetched times, domain class, and content hash.

Bind returned `symbol`, `security_id`, `as_of`, and manifest to the request. Add citations to the thesis and every factual “change my mind” trigger. `citations_used` must equal the union of actual claim evidence.

### Task 4.3 — Add deterministic verification before LLM review

Implement the verifier already envisioned in Fundamentals ×10:

- exact/normalized quote support against the supplied section;
- numeric and unit agreement against table cells within declared tolerance;
- temporal visibility and symbol/security match;
- source existence and content-hash match;
- contradiction and duplicate-claim checks;
- claim classification as `SUPPORTED`, `CONTRADICTED`, `STALE`, `OUT_OF_SCOPE`, or `UNSUPPORTED`.

Unsupported or contradicted material claims are struck. Any numeric mismatch or wrong-entity/wrong-date reference rejects publication. Store rejected run metadata and reasons without exposing its dossier as current.

### Task 4.4 — Improve document parsing and retrieval quality

Parse documents into versioned sections and tables rather than leading excerpts. Use page-aware pypdf layout extraction, targeted pdfplumber tables, and OCR only for image-heavy pages. Preserve raw PDFs and page anchors. Measure character coverage, empty-page rate, table fidelity, section recall, and OCR confidence.

Retrieve by question/section need with diversity across annual report, results, transcript, rating rationale, exchange announcement, and independent sources. State when management-supplied evidence is the only evidence. Detect conflicting values and retain both.

### Task 4.5 — Version the LLM workflow and enforce source hierarchy

Use a versioned LLM adapter, frozen system prompt, structured output, token/cost records, retry policy, and exact model ID. Recommended workflow:

1. deterministic pack readiness gate;
2. evidence extraction/normalisation;
3. synthesis into bull, bear, governance, valuation, catalysts, and data gaps;
4. deterministic verification;
5. optional fresh-context challenge pass in deep mode;
6. final publication only from supported claims.

Primary filings and exchange data outrank company commentary, which outranks reputable independent reporting, which outranks aggregators. Social content is discovery-only. Recency, independence, directness, and conflicts must be shown separately from model confidence.

### Task 4.6 — Create a frozen dossier evaluation set

**Files:** new `research/eval.py`, git-tracked manifests/labels without copyrighted source bodies, `tests/test_research_eval.py`

Build at least 100 cases spanning large/small caps, banks/NBFCs, cyclicals, loss-makers, restatements, auditor qualifications, promoter pledges, corporate actions, missing evidence, contradictory sources, renamed issuers, and hostile prompt-like text inside filings.

Release gates:

- 100% schema, symbol, date, and manifest binding;
- 100% published numeric claims verified within tolerance;
- zero published unsupported/contradicted material claims;
- at least 98% citation completeness on labelled factual claims;
- at least 95% correct abstention on deliberately missing evidence;
- at least 90% section retrieval recall on the labelled set;
- no prompt injection from document text can alter system rules or tool scope;
- stable results across three repeated runs, with differences explained at claim level.

**Phase 4 exit gate:** three live pilot symbols from different sectors pass the verifier and human review; the 100-case suite passes; every published sentence can be traced to evidence or is clearly marked analysis/opinion.

## Phase 5 — CI, operations, and security that protect research quality

**Duration:** 1–2 weeks, parallel only where it cannot change research definitions

### Task 5.1 — Add risk-weighted CI

Install from a committed lock file. Run Python 3.13 tests, Ruff, migration tests, no-network tests, deterministic golden tests, and a clean-database mini pipeline. Set aggregate coverage to at least 85%, but also require at least 90% branch coverage for PIT readers, quality gates, manifests, experiment registry, returns, verifier, and research pack. Ingestion parsers require fixture coverage for success, malformed, truncated, renamed-field, duplicate, and blocked-source cases.

### Task 5.2 — Add reproducibility and property tests

Run the same mini backtest twice and require byte-equivalent metrics/manifests. Property tests should cover no future visibility, split invariance, weights summing to exposure, caps, monotonic costs, no negative cash beyond tolerance, stable upserts, append-only ledgers, and schema migration idempotence.

### Task 5.3 — Improve health, alerts, and recovery

Health must include source freshness, latest successful manifest, feature/rating/research age, unresolved blockers, document parse failure rate, and backup age. Telegram should alert on actionable transitions and recoveries. Test backup restore into a temporary directory monthly and compare row counts and manifest hashes.

### Task 5.4 — Apply proportional security hardening

Use constant-time bearer comparison, `chmod 600` and owner checks for `.env`, bounded request sizes/timeouts, safe path handling, redacted logs, and rate limiting before remote exposure. Keep hostile-Markdown regression tests; the current renderer already escapes raw HTML.

**Phase 5 exit gate:** a clean clone installs reproducibly, passes all gates without network, runs a fixture end-to-end pipeline, restores the latest backup, and exposes no secret in logs or artifacts.

## Phase 6 — Ongoing research programme

### Sleeve L

Track prospective performance from the post-repair freeze date. Publish monthly forecast-versus-outcome attribution, rank stability, realized costs, coverage drift, and reason codes for every entry/exit. Promote from `BACKTEST_PASS` to `PROSPECTIVE_VALIDATED` only after the sealed 12-month bar passes.

### Sleeve S

Register one low-turnover economic hypothesis after the harness is frozen. The search budget should cover a small fixed set of 8–12 week holds and one signal family whose expected gross edge exceeds conservative costs. Failure remains a useful result; do not iterate against the sealed holdout.

### Champion/challenger governance

Keep the current production engine fixed as champion. Challengers run shadow-only with separate IDs. Promotion requires a sealed protocol, integrity gates, material improvement after costs, stability across cohorts, and documented reasons the edge should persist.

---

## 6. Recommended sequence and effort

| Stage | Work | Estimated focused effort | Dependency |
|---|---|---:|---|
| 0 | Claim states, manifests, baseline archive | 2–3 days | None |
| 1A | Temporal identity, valuation, controls | 7–12 days | Stage 0 |
| 1B | As-reported filings and survivorship backfill | 10–20 days plus unattended downloads | Stage 0; can overlap 1A |
| 2 | Return model, experiment registry, diagnostics, revalidation | 10–15 days | Stage 1 gates |
| 3 | Fundamentals ×10 deterministic engine | 15–25 days | Repaired spine; reuse existing plan |
| 4 | Evidence-grounded dossiers and evaluation | 10–20 days | Stable metrics/documents |
| 5 | CI, monitoring, recovery, security | 5–10 days | Interfaces stable; CI begins earlier |
| 6 | Prospective validation | 12 calendar months | Corrected version frozen |

For one engineer, expect roughly 10–16 focused weeks before the bot is audit-ready, plus the prospective observation window. Data-source access and historical issuer matching are the largest schedule risks.

---

## 7. Verification matrix

| Invariant | Automated proof | Release threshold |
|---|---|---|
| No future facts | Poison-row PIT tests + sampled time-travel audit | Zero unexplained leaks |
| Entity continuity | Rename/reuse/merger/delist fixtures | Zero ambiguous primary identities |
| Split-invariant valuation | Hand-worked and full-panel counterfactual | ≤2% unexplained discontinuity |
| Historical coverage | Per-date/cohort coverage report | 95% names, 98% traded value, or narrower claim |
| Reproducibility | Clean DB rebuild + manifest comparison | Identical manifest and metrics |
| Protocol integrity | Sealed experiment registry | No unregistered claimed run |
| Statistical robustness | Nested folds, bootstrap, trial ledger, sensitivities | All registered acceptance checks pass |
| Dossier grounding | Deterministic verifier + labelled evaluation set | Zero published unsupported material claims |
| Numeric accuracy | Cell/formula/unit verification | 100% on published numbers |
| Operational freshness | Quality gate and health checks | No unresolved blocker; sources within SLA |
| Recovery | Automated restore rehearsal | Restore and hash verification pass |

---

## 8. Immediate next ten actions

1. Change the public/internal Sleeve L state to `PROVISIONAL_REVALIDATION_REQUIRED`; keep the numerical report available with reasons.
2. File separate execution plans for Phase 0 and Phase 1 rather than continuing directly into rating/graph/LLM features.
3. Add manifest and experiment-registry schema before more durable data is loaded.
4. Correct the new schema's version/audit keys while the new tables are still empty.
5. Implement temporal security identity and the split-invariant valuation test.
6. Run the old-versus-corrected corporate-action counterfactual over all 117 feature dates.
7. Establish as-reported XBRL provenance and quantify survivorship by fold/cohort.
8. Resolve the impact-cost and risk-free specification drift and adopt an authoritative benchmark lane.
9. Rebuild Sleeve L under a sealed, nested protocol and downgrade or promote it based on the result.
10. Only then continue the Fundamentals ×10 research/verifier tasks, followed by the frozen dossier evaluation set.

---

## 9. Final decision rule

The bot is ready to make a trustworthy research claim only when a reader can answer, from the stored output alone:

1. What exact issuer/security and date does this concern?
2. What information was genuinely visible then?
3. Which immutable artifacts and transformations produced the number?
4. How complete, stale, conflicted, or revised were the inputs?
5. Which registered hypothesis and full trial count produced the performance claim?
6. How sensitive is the result to plausible data, execution, benchmark, and cost choices?
7. Which evidence supports each narrative claim and did an independent verifier confirm it?
8. Can the result be rebuilt on a clean database with the same manifest and metrics?

Until all eight have evidence-backed answers, the system should provide useful diagnostics and research leads, but not an unqualified validated recommendation.
