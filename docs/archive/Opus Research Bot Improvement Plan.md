# Opus Research Bot Improvement Plan

**Repository:** `sumaer123/research-bot` (`eqr`) · single-user, localhost-on-Mac, personal Indian-equity research engine · LLM budget ≈ $130/mo (cap $150)
**Date:** 2026-09-14
**Supersedes/synthesises:** `Research bot - codex improvement plan.md` (Codex) and `Research bot, improvement plan by Genie One.md` (Genie One), and governs the in-flight `docs/superpowers/plans/2026-09-14-fundamentals-x10-plan.md` (Fundamentals ×10).
**Status of this document:** working analysis + roadmap. Not implementation. Nothing here is built until Sumaer says go, phase by phase.

---

## 0. What this is, and why it exists

Three plans now sit on this project. They are not equals:

- **Codex** produced the correct **diagnosis** — the real, severe point-in-time and protocol defects that decide whether Sleeve L's "VALIDATED / 28.7% CAGR" claim means anything. Its evidence table (§1.3) is the most valuable single artifact in the project.
- **Genie One** produced a **tactical punch-list** — mostly hygiene, with two genuinely useful items (survivorship, CI) and two stale ones. It is superficial on the actual scientific risk.
- **Fundamentals ×10** is an **approved, in-flight feature-expansion** (T1.1–T1.4 already committed on `main`; ~30h XBRL backfill imminent). It adds *depth*, not *trust*.

This plan does one thing the other three don't: it **separates trust from everything else, and optimises for trust first**, at a scope proportional to a one-person localhost tool — not a regulated institution.

**The thesis in one paragraph.** The dominant question is not "is the code elegant" or "are there more features" — it is *whether the Sleeve L edge is real, or an artifact of a configuration seen once on a survivor-only, boom-heavy window using as-restated fundamentals no one could see at decision time.* Codex proved that question is currently **unanswerable** from the stored output. Two facts settle the path: (1) the historical holdout is **burned** — it was inspected repeatedly during repairs, so no historical test can ever again be a clean out-of-sample proof; (2) the fundamentals lane is **as-restated, not as-reported** — every statement row was first fetched on 2026-09-14. Therefore the *only* clean proof left is a **prospective, pre-registered, live-maturing out-of-sample ledger**, and everything historical is now supporting evidence, not proof. Optimise accordingly: start the prospective clock now, fix the trust-blocking bugs leanly, right-size the audit machinery, and never let the in-flight ×10 build outrun its provenance.

---

## 1. Verdict on the Codex plan

| Dimension | Verdict |
|---|---|
| Diagnosis (§1.3 evidence, P0/P1 findings) | **Adopt wholesale.** Every P0 is genuine and verifiable. This is the best work of the three. |
| Prescription scope | **Right-size.** Codex applies regulatory-grade audit infrastructure (5-identity cryptographic manifests at every boundary, full temporal issuer/ISIN/merger master, sealed experiment registry, 100-case labelled eval set, 85% CI coverage) to a single-user localhost bot. 10–16 weeks + 12 months is a research institution's program, not one person's tool. |
| Sequencing | **Fix.** The prospective live-OOS ledger — the only clean proof left — is buried at Phase 6. It has zero engineering dependency on the historical repairs and costs 12 *wall-clock* months. Pull it to day one, in parallel. |
| Snapshot currency | **Fix.** Codex reviewed `main@20b73ea` ("only T1.1/T1.2 done"). The live ×10 ledger shows T1.3 (PK already amended) and T1.4 done/near-done, T1.5 next. Govern the live ledger, not a stale commit. |
| XIRR certification | **Missing.** No return figure is certified; the headline is time-weighted CAGR presented as if it were an investor return. Added below as a HARD rule. |

**What to keep verbatim from Codex:** the honest claim-state ladder (DIAGNOSTIC → PROVISIONAL → BACKTEST_PASS → PROSPECTIVE_VALIDATED); the as-reported/as-restated/observed **truth-lane** distinction; the split-invariant valuation counterfactual; the "count *all* trials, the holdout is burned" governance; the deterministic evidence verifier for dossiers; the final trust test (§9 here).

**What to cut or defer from Codex** (see §7 for the full YAGNI log): cryptographic `data_manifest_sha` at every boundary → a lightweight provenance stamp; the full merger/demerger/ISIN temporal master → the minimal identity the two real bugs need; the 100-case eval set → a ~12-case adversarial set; 85% aggregate coverage → targeted tests on the modules that can silently corrupt a claim.

---

## 2. The optimisation principle

Rank every proposed item against one question: **does this change whether I can trust a number, today, for a single user on localhost?** Then:

1. **Anchors over audit theatre.** A fact's trustworthiness is proven by an anchor that can't argue back — a real filing, a re-derived number, a test that ran, a live forward observation — not by a SHA manifest that merely proves *consistency* with itself. Build the anchor; skip the ceremony that only re-states it. *(graph-of-loops: anchors over consensus.)*
2. **Right-size to the deployment.** Localhost + single user + one operator who is also the only reader. Constant-time bearer compare, rate limiting, HTML sanitisers, 100-case eval suites, and merger/demerger identity graphs are institutional controls; here they are low-priority until an external surface (the Upstox advisor API, R6) actually exposes the bot.
3. **Provenance-lite, not provenance-absent.** You do not need a cryptographic manifest to answer "was this fact visible then." You need `source_lane` + `observed_at` + `source_published_at` + a code-commit stamp on the run. That answers Codex's eight trust questions at ~10% of the build cost.
4. **Parallelise the wall clock.** The 12-month prospective window is the binding constraint on when the bot can *ever* be called validated. It starts the moment a config is frozen, and it depends on nothing else. Start it first.

---

## 3. Priority-ordered workstreams

### A — Trust the claim (highest priority; adopt Codex's diagnosis, lean fixes)

The trust-blocking bugs. These are not optional and they are not big.

- **A1. Honest relabel + protocol-drift one-liners (days, not weeks).** Relabel Sleeve L `PROVISIONAL` everywhere (dashboard, digest, advisor payload, README, VALIDATION.md) with reason codes; Sleeve S stays `DIAGNOSTIC`. Reconcile the cost coefficient to one value in code + docs + reports. Wire `EQR_RISK_FREE_PCT` (or delete it and version the assumption in the run). These are the cheapest, highest-integrity wins in the whole plan — do them first.
- **A2. As-reported vs as-restated truth lanes.** Stamp every statement fact with `source_lane` (`AS_REPORTED` | `AS_RESTATED_SECONDARY` | `OBSERVED`), `source_published_at`, `observed_at`, `revision_id`. Screener history → `AS_RESTATED_SECONDARY` (labelled, honest). XBRL/PDF from FY2018 → `AS_REPORTED` (this is exactly what ×10 is already building — see workstream C, this is where the two plans *fuse*). Pre-2018: either authenticate or **exclude the fundamental factor from the primary PIT claim** rather than promote 2026 history to as-reported. The primary validation lane must contain no fact first observed after its decision date without an authenticated period artifact.
- **A3. Split-invariant valuation.** Fix `features/price.py` × `features/fundamental.py`: never mix current `face_value` with historical raw close. Compute market cap from contemporaneous raw close × contemporaneous shares, *or* adjusted close × adjusted shares — one consistent basis. Then run the **old-vs-corrected counterfactual** over all 117 feature dates (rank correlation, changed holdings, ΔCAGR/ΔSharpe/ΔIR). This is a bounded, verifiable fix with a concrete acceptance bar (≤2% pre/post-action market-cap discontinuity absent genuine issuance).
- **A4. Historical exclusion controls.** Backfill ASM/GSM/F&O/ETF/industry snapshots where reliable archives exist; where they don't, **remove the filter from both strategy and benchmark** for that period rather than pretending today's snapshot existed then. Report controlled-period vs full-period sensitivity.
- **A5. Survivorship closure — reconciled with ×10.** Resolve ~450 delisted/renamed names by ISIN/BSE-code/filing-feed. Report coverage per fold (name count, traded-value weight, sector). Run three universes: complete-as-reported, observed-only-with-coverage, adverse-sensitivity (missing names get conservative ranks). *Reconciliation:* the ×10 XBRL-from-FY2018 spine is the primary as-reported source for these names — do not build a parallel screener-scrape path (Genie's suggestion); route delisted-name fundamentals through the ×10 XBRL loader.
- **A6. Minimal temporal identity (not the full master).** Build only what A3+A5 need: `instrument_as_of(symbol, date)` returning one security or a named ambiguity, so a reused ticker never splices two issuers, and historical z-score industry groups come from the contemporaneous taxonomy. **Defer** the full merger/demerger/ISIN-transition graph until a real case bites (YAGNI — §7).

### B — Start the prospective clock NOW (the centerpiece; parallel; zero dependency)

The one thing that can *actually* validate this bot, and it costs wall-clock time that starts today.

- **B1. Freeze a config and open a prospective verdict ledger.** From a named freeze date, record — append-only, forward-only — the live monthly Sleeve L ranks/weights the *current* engine produces, and each subsequent period's realised outcome. No lookback, no edits. This is the pristine OOS the burned holdout can no longer be.
- **B2. Same ledger for the ×10 rating engine (r1/r2/r3) and, later, any Sleeve S hypothesis.** Each engine version is a *separate* registered hypothesis with its own freeze date and its own maturing clock — never a revision of an earlier "validated" result.
- **B3. Promotion rule.** `BACKTEST_PASS` (historical, caveated) → `PROSPECTIVE_VALIDATED` only after ≥12 sealed forward months with no logic/data-definition change. The moment logic or data definition changes, the clock resets with a new version.

Because B depends on **nothing** in A/C/D, it starts on day one. Every week it doesn't start is a week added to the earliest possible honest "validated."

### C — Govern the in-flight ×10 build (time-sensitive; blocking gate)

×10 is adding depth on top of a spine A is repairing. Two rules keep depth from cementing defects.

- **C1. Schema-key correction is a BLOCKING gate BEFORE the ~30h XBRL backfill.** While the new tables are still empty, correct the durable keys: `engine_version` in the `fund_metrics` PK; dossiers keyed by immutable `run_id` (retain accepted *and* rejected attempts); `dossier_claims` keyed by `(run_id, claim_id)`; append-only revision/audit tables. **Why blocking:** the ledger already learned this once — the T1.3 `period_start` PK fix had to land before backfill because fixing after data lands forces a full re-backfill. Same logic, higher stakes. This is the highest-urgency, lowest-effort item in the plan.
- **C2. Provenance-lite gates on every ×10 load (not cryptographic manifests).** Require raw SHA, filing/broadcast time, taxonomy version, units, scale, parser version, revision id on each XBRL/PDF load; validate XBRL totals against filed PDF and Screener; a disagreement is a `SOURCE_CONFLICT`, never a silent pick. Ratings/calibrations carry the code-commit + source-lane stamp from principle §2.3 — not a five-identity manifest.
- **C3. r1/r2/r3 are separate hypotheses.** Each rating engine version calibrates independently on the repaired data and matures in the prospective ledger (B2) before it may be called anything but diagnostic. Fold ×10's own verified-dossier verifier into workstream E rather than duplicating it.

### D — Right-sized validation governance

Codex's statistics, minus the sealed-registry ceremony.

- **D1. One authoritative return + benchmark model.** Credit actual dividends; handle splits/bonuses/rights/mergers/suspensions consistently; use a dated risk-free (or a versioned fixed assumption stamped on the run). Prefer an official NIFTY 500 TRI; if unavailable, label the price+1.3% proxy prominently and run a yield sensitivity. Hand-worked golden tests reconcile split/bonus/dividend/rights/merger/delist to the rupee.
- **D2. Trial honesty (registry-lite).** Record, in a plain append-only file per experiment: hypothesis, data lane, feature version, grid, cost model, benchmark, folds, purge/embargo, acceptance bar, holdout — before the run. Increment a research-trial counter on *every* exploratory run and material repair (not just `len(grid)`). Recompute Deflated Sharpe on the *true* trial count. No cryptographic seal needed — a committed file + git history is the audit trail for one user.
- **D3. Nested, leakage-aware validation.** Fit winsorisation/transforms/feature-inclusion/thresholds on the training portion only; purge the max feature/holding overlap; embargo the forecast horizon; date-ordered, never random splits. Report bootstrap CIs for CAGR/Sharpe/IR/drawdown, probability of underperforming, and per-year/per-symbol excess contribution so the 2021/2023 dependence is visible.
- **D4. Coverage-aware scoring.** Normalise partial Piotroski by `f_known`; separate *score* from *confidence* and *eligibility*; don't let low-coverage names win a rank through weight renormalisation.
- **D5. Revalidate Sleeve L once, honestly.** One-variable counterfactuals (statements, identity, valuation, exclusions, returns, benchmark, costs), then the combined corrected engine; attribute the delta. **Downgrade rule:** any single plausible correction moving CAGR >2pp, Sharpe/IR >0.10, or >20% of holdings forces a new engine version and root-cause. Sleeve L emerges as `BACKTEST_PASS` (caveated) or stays `PROVISIONAL` — never straight to VALIDATED.

### E — Dossier grounding (verifier yes; heavy eval no)

The dossier layer is a prototype (0 stored dossiers, 1 symbol's docs). Build the load-bearing part; skip the institutional suite.

- **E1. Fix the pack temporal contract.** Filter every pack read by `filing_dt <= as_of`; no current Screener meta / current classification in a historical pack; bind the returned symbol + as_of + rating to the request. Poison-row tests (future filing, future classification, unrelated symbol, doc published one second after cutoff) — none may appear.
- **E2. Deterministic evidence verifier (the real value).** Every claim carries a typed evidence atom (table cell with unit + `visible_from` + artifact SHA, or exact quote + doc/section/page + publication time, or formula + inputs + tolerance). The verifier checks quote support, numeric+unit agreement, temporal visibility, entity match, source existence. Unsupported/contradicted material claims are struck; any numeric or wrong-entity/wrong-date reference rejects publication. Store rejected runs (not as current).
- **E3. Small adversarial eval set (~12 cases, not 100).** Cover the nasty categories that actually break groundedness: restatement, promoter pledge, auditor qualification, deliberately-missing evidence (must abstain), contradictory sources, renamed issuer, and **prompt-injection text inside a filing**. Grow toward 100 only if/when dossiers become load-bearing for real decisions.

### F — Ops, CI, security (targeted, not coverage-chasing)

- **F1. CI on a committed lock file:** py3.13 tests, migration tests, no-network tests, deterministic golden tests, a clean-DB mini-pipeline. **Do not chase an aggregate coverage %** — target real tests on the modules that can silently corrupt a claim (PIT readers, quality gate, returns, valuation, verifier). Coverage is a proxy; the anchor is "the dangerous modules are tested." (Genie's 60% is too low; Codex's 85% is gold-plating.)
- **F2. Enforceable, resolvable quality gates.** Add severity + affected slice + waiver metadata; a run refuses unresolved `BLOCKER`s for its input; `--force` demands a reason and records a non-validatable state.
- **F3. Health + Telegram** on actionable transitions (stale source, unresolved blocker, parse-failure spike, backup age) — not job-completion spam. Monthly backup-restore rehearsal into a temp dir, row-count + provenance-stamp compared.
- **F4. Proportional security — LOW until the advisor API is exposed (Upstox R6).** Then, together: constant-time bearer compare, `chmod 600` + owner check on `.env`, bounded request sizes/timeouts, rate limiting, redacted logs. On localhost today these are low-priority. Keep hostile-Markdown regression tests (the renderer already `html.escape`s — Genie's sanitiser item is correctly **dropped**).

---

## 4. XIRR-engine certification (HARD standing rule — folded in)

Neither prior plan certifies a single return, and both let a **time-weighted** CAGR read like an investor's return. The rules:

1. **Every money-weighted / annualised return the bot surfaces MUST be certified by the standalone XIRR engine via the `xirr` agent** — recomputed from the same dated cash flows, agreeing within tolerance. An app-computed return is UNTRUSTED until independently certified.
2. **Label the headline honestly.** The current "28.7% CAGR" is a *time-weighted* backtest return, not an XIRR. It must be labelled as such and never presented as the return an investor would have earned.
3. **Never quote a rate without its capital base** ([[xirr-needs-a-capital-base]]). If the prospective ledger (B) ever reports a realised return on a simulated capital base with dated inflows, that figure **is** an XIRR — certify it via the engine and sanity-check against `(1 + simple)^(365/days)`.

---

## 5. Disposition tables

### 5a. Codex phases → this plan

| Codex phase | Disposition | Where it lands here |
|---|---|---|
| P0 findings (§1.4) | **Adopt all** | Workstream A |
| Phase 0 (claim states, manifests, baseline) | Keep claim states + baseline; **right-size manifests** to provenance-lite | A1, §2.3 |
| Phase 1 (temporal identity, PIT lanes, survivorship, valuation, controls, gates) | Keep; **trim identity master to the minimum** | A2–A6, F2 |
| Phase 2 (returns, registry, nested folds, diagnostics, revalidate) | Keep; **registry-lite, not sealed** | D1–D5 |
| Phase 3 (×10 deterministic engine) | Keep; **schema-fix is a blocking pre-backfill gate** | C1–C3 |
| Phase 4 (evidence-grounded dossiers, 100-case eval) | Keep verifier; **eval → ~12 adversarial cases** | E1–E3 |
| Phase 5 (CI/ops/security 85% coverage) | Keep; **target risky modules, defer security to R6** | F1–F4 |
| Phase 6 (prospective validation) | **Promote to day-one, parallel** | Workstream B |
| 5-identity manifest everywhere | **Cut → provenance-lite stamp** | §2.3, §7 |
| Full merger/demerger/ISIN master | **Defer until a real case bites** | A6, §7 |

### 5b. Genie One items

| Genie item | Disposition |
|---|---|
| Close survivorship gap | **Keep**, route through ×10 XBRL, not a screener-scrape (A5) |
| Panel-adjustment materiality | **Keep**, subsume into the A3 valuation counterfactual |
| `statements_as_of` PIT test | **Already exists**; add real-artifact + revision + mixed-basis tests instead |
| Add CI | **Keep**, strengthen to risk-weighted (F1) |
| Constant-time bearer compare | **Keep, LOW** — do at R6 API exposure (F4) |
| Configure Telegram | **Keep** as ops (F3) |
| Backtest quality gate | **Keep, redesign** with waiver metadata (F2) |
| Remove `yfinance` | **Keep** (unless a documented provenance-contracted adapter is added) |
| Pin dependencies | **Keep** + numerical golden tests (F1) |
| `visible_from` on `instruments` | **Replace** — a symbol-keyed row still overwrites history; use minimal temporal identity (A6) |
| Sanitise `md_render` | **Drop** — renderer already escapes; keep regression tests (F4) |
| `chmod 600 .env` | **Keep, LOW** (F4) |
| Add Ruff | **Keep, LOW** — after integrity work |
| Sleeve S redesign / advisor / VM | **Keep deferred** — none improves research validity today |

### 5c. Fundamentals ×10 reconciliation (against the LIVE ledger, not the stale snapshot)

- **Live state:** Phase 0 complete (6 GO); T1.1 done (21 tables); T1.2 done (`20b73ea`); T1.3 done with PK amended to include `period_start`; T1.4 done/near-done; **T1.5 next**. (Codex's "only T1.1/T1.2 done @ `20b73ea`" is stale — govern the ledger.)
- **Fusion point:** ×10's XBRL-from-FY2018 spine **is** workstream A2's `AS_REPORTED` lane and A5's delisted-name source. They are not competing — A defines the *provenance contract*, ×10 delivers the *data* under it.
- **Blocking dependency:** C1 (schema-key fix) must land before the ~30h backfill; A1 (relabel + protocol drift) should land before any new validation numbers are quoted.

---

## 6. Sequencing (effort vs wall clock)

| Track | Work | Focused effort | Wall clock | Runs in parallel with |
|---|---|---|---|---|
| **Now, day 1** | A1 relabel + protocol drift; **B1 open the prospective ledger**; C1 schema-key fix before backfill | 2–4 days | — | each other |
| **A-spine** | A2 truth lanes, A3 valuation + counterfactual, A4 controls, A5 survivorship (via ×10), A6 minimal identity | ~2–3 weeks | — | B (always), C2 loads |
| **D-validation** | returns/benchmark, registry-lite, nested folds, revalidate Sleeve L | ~1–2 weeks | — | after A gates pass |
| **C/×10 depth** | continue T1.5→ with provenance-lite gates; r1 calibration on repaired data | reuse ×10 estimate | — | after C1 + A2 |
| **E-dossiers** | pack contract, verifier, ~12-case eval | ~1–2 weeks | — | after C data stabilises |
| **F-ops** | CI, gates, health, backups | ~3–5 days | — | can start early |
| **B-prospective** | the maturing clock | — | **12 months** | everything |

For one operator (Sumaer + agents): roughly **5–8 focused weeks** to `BACKTEST_PASS` with honest caveats — versus Codex's 10–16 — by cutting the audit ceremony and fusing A5 into ×10. The **12-month prospective window is the true gate** to `PROSPECTIVE_VALIDATED`, and it is already running the day B1 opens.

---

## 7. YAGNI cut-list + decision log

| Cut / deferred | Why it's safe for a single-user localhost bot |
|---|---|
| Cryptographic `data_manifest_sha` at every boundary | A code-commit + source-lane + `observed_at` stamp answers "was it visible then" and "can I rebuild it." The SHA proves self-consistency, which no one is disputing. Cost >> value here. |
| Full merger/demerger/ISIN/ticker-reuse temporal master | Build only `instrument_as_of` (one security or named ambiguity). The full event graph is real work for cases that may never occur in this universe; add it when one bites. |
| Sealed experiment registry with hash seals | A committed plain-text pre-registration + git history is a sufficient audit trail for one user. Increment the true trial count; skip the seal ceremony. |
| 100-case labelled dossier eval set | Start at ~12 adversarial cases. The dossier layer has 0 stored dossiers — a 100-case suite is premature infrastructure. |
| 85% aggregate CI coverage | Target the modules that can silently corrupt a claim; let aggregate fall out. Chasing a number invites test theatre on cheap paths. |
| Constant-time compare, rate limiting, `.env` chmod, size/timeout bounds | LOW until the advisor API is exposed to Upstox (R6). Localhost single-user removes the threat model these address. |
| `md_render` sanitiser | Renderer already `html.escape`s; a second sanitiser is redundant. Keep regression tests. |

**Decision log:** (1) Trust before depth before elegance. (2) Prospective ledger is day-one, not Phase 6 — it's the only clean proof and it costs wall-clock time. (3) Schema-key fix is a blocking pre-backfill gate — re-backfill is the expensive failure mode. (4) A5 survivorship routes through ×10 XBRL, not a parallel scrape. (5) Provenance-lite over cryptographic manifests. (6) Every money-weighted return is XIRR-engine certified; the current headline is time-weighted and labelled so.

---

## 8. Open items that need Sumaer

- **Empty `ANTHROPIC_API_KEY`** — blocks the ×10 verified-dossier live smoke (Phase-6 dependency in ×10; workstream E here). No spend until supplied.
- **Official NIFTY 500 TRI access** — decide: license/obtain the true TRI, or accept the labelled price+1.3% proxy with a yield sensitivity (D1).
- **Prospective freeze date** — pick the date B1's clock starts; earlier is strictly better.
- **Telegram token + chat id** — for F3 alerting.
- **VM (Hetzner/GCP Mumbai)** — still deferred; only needed when the advisor API must be reachable off the Mac (Upstox R6). OCI stays Upstox-only.
- **Parked Mac-deploy grant** — commit `06e35a1` local, blocked by the auto-mode classifier; needs Sumaer's go or a standing grant to push via production-engineer.

---

## 9. The trust test (adopted from Codex, trimmed)

The bot may make a trustworthy research claim only when a reader can answer, **from the stored output alone**:

1. What exact issuer/security and date does this concern?
2. What information was genuinely visible then (which truth lane)?
3. Which artifacts and transformations produced the number?
4. How complete, stale, conflicted, or revised were the inputs?
5. Which pre-registered hypothesis and **true** trial count produced the performance claim?
6. How sensitive is it to plausible data / execution / benchmark / cost choices?
7. Which evidence supports each narrative claim, and did the deterministic verifier confirm it?
8. Can it be rebuilt on a clean database to the same numbers — and is any money-weighted return XIRR-engine certified?

Until all eight have evidence-backed answers, the bot ships **useful diagnostics and research leads — never an unqualified validated recommendation.**
