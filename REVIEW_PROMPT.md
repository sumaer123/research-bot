# Review Brief — Sumaer Research Bot (`eqr`)

**Paste everything below the line into a fresh agent session. It is self-contained.**

---

## 0. Your assignment

You are an independent reviewer. Do a **full technical and research-methodology review** of the
Sumaer Research Bot (`eqr`) repository, then produce a **prioritised improvement plan**.

This is a **read-mostly engagement**. You may run tests, linters, static analysis, and throwaway
scripts. You may **not** refactor the codebase, "fix things as you go", or rewrite docs. Your two
deliverables are documents (§6). If you find a one-line bug so severe it invalidates a published
result, report it — do not silently patch it.

The owner is a non-fulltime engineer running this as a personal research project. Optimise your
recommendations for **correctness of the research claims first, then operational reliability, then
code elegance last**. A finding that says "the backtest may be biased" is worth 100x a finding that
says "this function is too long".

---

## 1. Repository and access

- **Repo:** `https://github.com/sumaer123/research-bot` (owner `sumaer123`)
- **Default branch:** `main`. HEAD at time of writing: `8be2e88`
- **Work branch for your deliverables:** create `claude/eqr-review-<short-slug>` off `main`.
  **Never push to `main`.** Open a **draft PR** when done.
- **Sibling repo, for context only:** `https://github.com/sumaer123/project-upstox` — a separate
  live trading system. `eqr` is designed to advise it later over a read-only HTTP API. **Do not
  modify project-upstox.** Read it only if you need to judge the advisor contract's fit.

### Environment reality check — read this before you plan your review

- The repo ships **no data**. `data/` is gitignored: the DuckDB file (`data/eqr.duckdb`), raw NSE
  archives, validation reports under `data/reports/validate-*/`, and PDFs all live only on the
  owner's Mac.
- **Therefore you cannot re-run the backtests or reproduce the published performance numbers.**
  Do not pretend otherwise. Your validation review must be a review of *the code that produced
  the numbers* and *the protocol as documented* — a white-box audit for bias, not a replication.
  Where a claim can only be settled by re-running on real data, say so explicitly and write the
  exact command the owner should run to settle it.
- Target runtime is **Python 3.13** with `uv`. Setup:
  ```
  uv venv --python 3.13 .venv
  uv pip install --python .venv/bin/python -e '.[dev]'
  .venv/bin/python -m pytest
  ```
  If Python 3.13 is unavailable in your container, try 3.12/3.11 and **report any test failure
  that is an artefact of the version mismatch separately** from real failures. Test suite is
  offline (fixtures only) — it should not need network.
- Network access to NSE/screener.in from a datacenter IP is usually blocked. Do not treat a live
  fetch failure as a code defect without checking `eqr/spine/http.py` first.

---

## 2. What the project is

Personal, independent Indian-equity research engine. It ranks the full NSE universe with a
point-in-time (PIT) quantitative engine, validates any edge before trusting it, and writes
Claude-authored research dossiers grounded in stored filings. It emits **target weights only** —
there is deliberately **no order path anywhere in the repo**. It is intended to advise the
separate Project Upstox system later as one fail-soft evidence line that can add at most one
line's worth of points and can never remove a gate.

**Scale:** ~4,500 LOC in `eqr/`, ~800 LOC of tests across 14 test modules, 28 DuckDB tables,
7 docs, 4 launchd agents + 5 systemd units.

### Layer architecture (strict; a layer never calls another layer's fetchers)

```
NSE archives/API, screener.in
        |  fetch -> data/raw/ (immutable)
        v
   eqr/store        data/eqr.duckdb -- schema.sql, connect/init, upsert, as_of_view (PIT reads)
        ^
        |  curated rows (as_of + visible_from)
   eqr/spine        archives . nse_api . screener . adjust (split/bonus) . universe . quality
        v
   eqr/features     price / fundamental / valuation factors -> cross-section z-scores
        v
   eqr/strategy     regime . Sleeve L (monthly) . Sleeve S (weekly) . sizing . rank
        v
   eqr/validate     costs . backtest . walk-forward . deflated Sharpe . acceptance bar . reports
        v
   eqr/research     docstore (filings) . pack (JSON evidence pack) . dossier (Claude, cited)
        v
   eqr/surfaces     web (FastAPI dashboard) . advisor API . Telegram digest
```

Key entry points: `eqr/cli.py` (368 LOC, all commands) · `eqr/store/schema.sql` (schema of record)
· `eqr/validate/walkforward.py` + `eqr/validate/backtest.py` (where bias would hide) ·
`eqr/store/pit.py` (`as_of_view`, the PIT contract) · `eqr/spine/adjust.py` (corporate actions) ·
`eqr/surfaces/advisor_client.py` (the fail-soft reference client Upstox would copy).

### The two sleeves

- **Sleeve L — Compounders**, monthly rebalance. Score = 0.30 quality + 0.25 value + 0.30 momentum
  + 0.15 low-risk, industry-relative z-scores. Universe: >=250 sessions history, close >= Rs 20,
  median 120-day traded value >= Rs 1 cr, not ASM stage >=2 / F&O-banned, `pat_ttm > 0`. Top 30,
  held while inside top 45 (rank hysteresis).
- **Sleeve S — Tactical**, weekly rebalance. Score = 0.40 1-day momentum + 0.30 breakout + 0.30
  delivery surge. Rs 3 cr liquidity floor. Top 20, held while inside top 30, hard stop -8%.
  No new entries in RISK_OFF.

Both emit inverse-60-day-vol target weights, capped 5%/name and 25%/industry, scaled by regime
exposure.

### Published validation verdicts (2026-09-14, first run of the pre-registered protocol)

- **Sleeve L: VALIDATED.** Stitched OOS 2019 -> Aug-2025, net of costs: CAGR 28.7% vs 17.1%
  (NIFTY 500 TR proxy), Sharpe 1.28 vs 0.73, max DD -22.2% vs -37.8%, IR 0.72, deflated-Sharpe
  p = 0.005 over 6 trials, 4/4 recent folds beat the index, median order 0.03% of ADV20 at Rs 10
  lakh. Holdout Sep-2025 -> Sep-2026 (evaluated once): 21.9% vs 1.9%, Sharpe 0.98. Selected
  configuration: N=20 momentum-tilt.
- **Sleeve S: NOT VALIDATED.** OOS Sharpe -0.22, IR -0.92, deflated-Sharpe p = 0.855, turnover
  ~2,000%/yr driving 1,180-1,360 bps/yr of cost. Exposed as a diagnostic line only.

Caveats the owner already documents and you should treat as **known, not as findings** (go deeper
than these): the 2018-19 small-cap bust sits inside the training window and the same configuration
shows 19.9% CAGR / -46% DD over the full 2017->2026 period; 2021 and 2023 carry much of the OOS
excess; **fundamentals survivorship bias** — delisted names keep price history but never had a
screener.in page, so Sleeve L's fundamentals cover only 823 of the 1,225 names in the 2017-21
universe; and the base configuration's full-period result was seen once before the protocol ran.

### Known open items (already on the owner's list — do not re-report as discoveries)

1. Survivorship gap for ~450 delisted names (Sleeve L fundamentals only). Not started.
2. Sleeve S redesign: next pre-registered experiment is 8-12 week holds with a signal that clears
   the cost line. A post-hoc minimum-hold run reached Sharpe 0.61 / 926% turnover but only matched
   the index after ~469 bps/yr costs.
3. VM not provisioned. The Mac (launchd, 4 agents) is production; `deploy/install.sh` and the
   systemd units are **untested against a real box**.
4. Telegram token unset, so `eqr digest --send` fails.

### Guardrails that constrain any recommendation you make

- No order path. Ever. Sizing produces target weights only.
- Dossiers never change ranks. Every dossier claim must cite a `[doc_id]` or a named table; an
  unsupported claim fails validation and the run is **rejected outright, never partially stored**.
- `data/` is gitignored — never committed. Secrets only in `.env`, never `.env.example`, never a
  doc. Only env-var *names* appear in docs.
- The Project Upstox OCI box is Upstox-only; this project is never deployed there.
- Public data sources only, <= 1 req/s, raw responses cached immutably.
- Docs are owned by a `documentation-engineer` agent and deploys by a `production-engineer` agent
  — so **do not hand-edit files under `docs/`**. Put your deliverables at the repo root (§6).

### Docs to read before you judge anything

`README.md` · `docs/DOCS_INDEX.md` (map) · `docs/REBUILD_SPEC.md` (rebuild from zero, env-var
names, data model, jobs) · `docs/DATA_SOURCES.md` (every source, cadence, PIT rule, failure mode)
· `docs/OPERATIONS.md` (runbook, quality checks, dossiers, open items) · `docs/VALIDATION.md`
(protocol, acceptance bar, fold tables) · `docs/superpowers/specs/2026-09-14-research-bot-design.md`
(**the approved design spec — the source of truth; read it first**) ·
`docs/superpowers/plans/2026-09-14-research-bot-plan.md` (15-task build plan).

---

## 3. Review dimensions

Cover all eight. Ordered by how much the owner cares. Spend your effort proportionally — roughly
half of it on A and B.

### A. Research validity and look-ahead bias (highest value)

This is the heart of the review. The entire project's value rests on "Sleeve L is VALIDATED"
being true. Attack that claim.

- **PIT integrity.** Read `eqr/store/pit.py` and every call site of `as_of_view`. Does every
  read path go through it? Is `visible_from` set correctly at every write — especially for
  fundamentals (screener.in has no publication timestamp), corporate actions, index membership,
  ASM/GSM surveillance status, and F&O ban lists? Find any query that reads a table directly and
  could see the future. Check for the classic leaks: restated fundamentals overwriting the
  originally-visible row; a universe filter computed on the full history; a z-score normalised
  using future cross-sections; an adjustment factor applied backwards over the whole series
  without regard to the as-of date.
- **Adjustment handling.** `eqr/spine/adjust.py` infers split/bonus factors from `PREV_CLOSE`
  restatements on the tape. Where does that break — partial recoveries, rights issues, mergers,
  name/symbol changes, demergers? What happens to a name whose symbol changed mid-history? How
  does `factor_anomalies` interact with the backtest?
- **Backtest mechanics.** `eqr/validate/backtest.py` and `eqr/validate/walkforward.py`. Check:
  signal-to-execution lag (are weights applied on the same bar they are computed from?),
  rebalance date alignment vs holidays, the rank-hysteresis implementation, the -8% stop
  mechanics for Sleeve S (intra-bar assumption?), cash/dividend treatment, and whether the
  NIFTY 500 TR "proxy" is actually total-return-comparable to a portfolio that ignores dividends.
- **Cost model.** `eqr/validate/costs.py`. Are brokerage, STT, exchange fees, stamp duty, GST and
  slippage all present and at plausible 2026 Indian retail rates? Is impact a function of order
  size vs ADV? At a 2,000%/yr turnover, cost-model error dominates the verdict — quantify the
  sensitivity if you can.
- **Statistics.** `eqr/validate/metrics.py` and `eqr/validate/acceptance.py`. Is the deflated
  Sharpe implemented correctly, and is the **trial count honest**? Six trials is the declared
  number — count the actual configurations the code sweeps and every decision made by looking at
  results. Is the holdout genuinely evaluated once? Is the acceptance bar checkable from the code
  or only from prose? Are the fold boundaries free of overlap with the feature-construction
  lookback windows (a 120-day median or a 252-day momentum window straddling a fold boundary
  leaks)?
- **Survivorship, beyond the documented gap.** The owner documents the *fundamentals* gap. Check
  for the other kind: does the **price/universe** history include delisted names at every as-of
  date, or does the universe get built from a current-day symbol list?

### B. Correctness of data ingestion and the spine

- Parsers: `eqr/spine/nse_archives.py` (3 bhavcopy formats, MTO, index closes, EQUITY_L, ban,
  deals), `eqr/spine/nse_api.py`, `eqr/spine/screener.py` (354 LOC — the most fragile file in the
  repo). Do they reject malformed input rather than guess? What happens on a silently changed
  column, a series-mix change, a partial file?
- Idempotency: is re-running `eqr refresh` for the same date safe? Are upserts real upserts on the
  documented key? Is `data/raw/` genuinely immutable?
- Schema: 28 tables in `eqr/store/schema.sql`. Are keys, types and NULL semantics right? **There
  is no migration mechanism** — assess what a schema change costs today and what the cheapest fix
  is.
- Error handling vs spec §10: fetchers must never raise past the orchestrator; every step logs a
  `FetchResult` to `fetch_log`. Verify that holds in `eqr/spine/refresh.py`.
- Quality harness (`eqr/spine/quality.py`): do the six documented checks actually fire, land in
  `quality_checks`, and do `validate`/`backtest` genuinely refuse a dirty date range without
  `--force`? Spec says "meant to" — confirm whether it is implemented.

### C. Testing

~800 LOC of tests against ~4,500 LOC of code, with no coverage gate and no CI. Measure real
coverage (`pytest --cov=eqr`). Report per-layer coverage, not just a headline number. Identify the
**highest-risk untested paths** — weight by blast radius, not by line count. Note that
`tests/test_launchd.py` (115 LOC) is larger than any strategy or validation test file; say whether
that allocation matches the risk. Assess whether the planted-signal test in the backtest is strong
enough to catch a lookahead regression, and propose the specific tests that would have caught the
bias classes you found in §A.

### D. Security

- Secret handling end-to-end: `.env` loading, the `EQR_ADVISOR_TOKEN` bearer check in
  `eqr/surfaces/web/app.py`, whether tokens can leak into logs, `fetch_log`, digests, or reports.
- Advisor API: is the token compared in constant time? Is the API genuinely disabled when the
  token is unset (documented as 503)? Is the web UI genuinely read-only? Any injection surface in
  the FastAPI routes or the Jinja templates (`autoescape` on?).
- **Prompt injection into the dossier path** — the one that matters. `eqr/research/dossier.py`
  feeds filings and announcements fetched from the public internet into a Claude prompt whose
  output is then schema-validated and stored. Can hostile text in a filing subvert the dossier,
  cause a fabricated citation to pass validation, or influence anything downstream? Does the
  `claude` CLI invocation shell out safely?
- Fetch layer: SSRF/proxy handling in `eqr/spine/http.py`, TLS verification, redirect handling,
  and whether `EQR_PROXY` can be abused.
- Deploy: file permissions in `deploy/mac/install-mac.sh` and `deploy/install.sh`, whether `.env`
  is world-readable, and whether `deploy/backup.sh` can leak the restic/B2 credentials.

### E. Operational reliability

- **There is no CI.** No `.github/` directory exists. This is likely the single highest-leverage
  gap in the repo — cost it and design the minimal version (the suite is offline, so it should run
  on a free runner in under a minute).
- Single point of failure: production is one Mac via launchd. Assess `deploy/mac/install-mac.sh`,
  the four plists, log rotation in `~/Library/Logs/eqr/`, what happens on reboot / laptop sleep /
  network loss, and whether a failed job is actually noticed by anyone.
- Backup: `deploy/backup.sh` (restic/B2). Is it wired into launchd at all, or only systemd? **Has
  a restore ever been tested?** An untested backup is not a backup — say so if that is the state.
- Untested systemd path + untested `deploy/install.sh`. Recommend whether to keep maintaining two
  deploy paths before the VM exists.
- Observability: what tells the owner that yesterday's refresh silently loaded a truncated
  bhavcopy? Is the Telegram digest the only alerting channel, and it is currently unconfigured?

### F. Code quality and architecture

- Is the strict-layering rule actually honoured, or does a layer reach past its neighbour?
- `eqr/cli.py` at 368 LOC is the largest module — is business logic leaking into it?
- Dependency hygiene: `yfinance` is a declared dependency — find where it is used and whether it
  contaminates the PIT guarantee (it is an adjusted-price source). No lock file is committed and
  all pins are `>=` floors: assess the reproducibility risk for a project whose whole claim is
  reproducibility.
- No linter or formatter is configured (`ruff`/`black` absent from `pyproject.toml`). Low
  priority, but say so once.
- Type hints, error types, logging consistency, dead code. **Keep this section short.**

### G. Documentation accuracy

The docs are unusually good; the risk is **drift**, not absence. Spot-check claims against code
and report only contradictions: every CLI command in `README.md`/`docs/REBUILD_SPEC.md` §8 exists
with those flags; every env var in `.env.example` is actually read; `docs/DATA_SOURCES.md` matches
the real URLs and cadences; the schema described matches `schema.sql`; the spec's §10/§11 claims
match the implementation. Note anything documented in the future tense that is already true, or
documented as true that is not.

### H. Product direction

Brief. Given Sleeve L is validated and Sleeve S is not, what is the highest-expected-value next
move for a personal research engine — closing the survivorship gap, the Sleeve S redesign, a third
sleeve, hardening the advisor contract for the Upstox R6 integration, or paying down the CI/ops
debt? Give one recommendation with reasoning, not a menu.

---

## 4. Method

1. Read the design spec first, then `README.md`, then `docs/VALIDATION.md`. Build a mental model
   of what the system *claims* before reading code.
2. Clone, set up the venv, run the test suite, record the exact result (pass/fail counts, any
   version-mismatch artefacts).
3. Run coverage. Read every file in `eqr/validate/` and `eqr/store/pit.py` line by line — these
   carry the research claim.
4. Trace one full path end to end with a concrete date: raw bhavcopy -> `prices_daily` ->
   feature at a month-end -> rank -> weight -> a backtest bar. Write down every point where a
   future value could enter. This trace is the most valuable thing you will do.
5. Then sweep the remaining dimensions.
6. Before writing anything up, re-verify each finding against the code. Discard what you cannot
   cite.

---

## 5. Standards for findings

- **Cite `file.py:line` for every finding.** No claim without a citation.
- **Severity:** `CRITICAL` (invalidates a published research result, or loses/corrupts data, or
  leaks a secret) · `HIGH` (will produce a wrong number or a silent outage) · `MEDIUM` (real risk,
  bounded blast radius) · `LOW` (hygiene). Be strict — inflating severity destroys the report's
  usefulness.
- **Confidence:** mark each finding `Verified` (you read the code and it is unambiguous),
  `Likely` (strong reading, one assumption), or `Unverified — needs a run on real data` (cannot be
  settled without `data/`). **Never present an unverified finding as verified.** If you do not
  know, write "do not know" and state exactly what would settle it.
- Every finding needs a **concrete failure scenario**: specific inputs or state -> specific wrong
  output. "This could be fragile" is not a finding.
- **No invented numbers.** Do not estimate performance impact, cost-model error, or coverage
  percentages unless you computed them. Quote the command and its output.
- Explicitly list what you **could not** review and why.

---

## 6. Deliverables

Two files at the **repo root** (not under `docs/` — that directory is agent-owned), on your work
branch, in a draft PR:

### `REVIEW.md`
1. **Verdict** — 5 bullets max. Is the Sleeve L VALIDATED claim trustworthy as it stands? Yes /
   no / not determinable without a data run. Lead with this.
2. **Findings table** — ID, severity, confidence, dimension, one-line summary, `file:line`.
   Sorted by severity.
3. **Findings in detail** — one section each: what, where, failure scenario, evidence, fix
   sketch. CRITICAL and HIGH get full treatment; MEDIUM gets a paragraph; LOW gets one line in a
   list.
4. **What I could not verify** — explicit, with the command that would settle each item.
5. **What is already good** — short, honest; the owner needs to know what not to churn.

### `IMPROVEMENT_PLAN.md`
1. **Sequenced workstreams**, each with: objective, the findings it closes, concrete tasks, a
   **done-when** criterion that is a test or a command with expected output, effort in
   half-day units, and dependencies. Mirror the style of
   `docs/superpowers/plans/2026-09-14-research-bot-plan.md` — a numbered table with a done-when
   column.
2. **Phasing:** Phase 0 = anything that must happen before the next published validation run is
   trusted. Phase 1 = reliability and CI. Phase 2 = capability (survivorship gap, Sleeve S
   redesign, advisor hardening). Phase 3 = nice-to-have. Be ruthless about what is really Phase 0.
3. **Explicit non-goals** — what you are recommending the owner deliberately *not* do, and why.
   Include anything a reasonable reviewer would suggest that conflicts with the guardrails in §2.
4. **Risk register** — for each Phase 0/1 item, what could break by doing it.

PR: draft, title `Review: eqr full technical and research-methodology review`, body = the verdict
bullets plus a link to each file. Do not modify any existing file in the repo.

---

## 7. Out of scope

- Refactors, rewrites, or "drive-by" fixes.
- Any change to `project-upstox`.
- Any recommendation that adds an order path, weakens the dossier citation requirement, commits
  `data/`, puts secrets in a doc, or deploys to the Upstox OCI box.
- Recommending paid data feeds, intraday data, or options as a Phase 0/1 item — all are declared
  out of scope for v1 in the design spec §14.
- Cosmetic style debate. One line in the LOW list is the whole budget for formatting.
