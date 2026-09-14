---
title: Research Bot — Final Recommended Plan
date: 2026-09-14
status: approved; Wave 1 shipped 2026-09-14
tier: reference (do not edit)
---

# Research Bot — Final Recommended Plan

Critical review of the Codex plan, and the roadmap to "best equity research analyst" with a comprehensive scoring mechanism. Project `Project Research Bot` (`eqr`). This document reconciles three prior plans (Codex integrity audit, Genie One hygiene punch-list, Opus synthesis) with the in-flight Fundamentals ×10 plan.

## Summary of what shipped in Wave 1 (2026-09-14)

Wave 1 changed no headline numbers — only what the system says about them and how it records provenance. Delivered across 7 commits (`2f7e2a4`, `d24b37c`, `17ba651`, `82c23b1`, `2fe8447`, `013b9ee`, `eba4b14`), 144 tests green, live-DB migration applied and verified:

- **W1.4** Corrected durable-table primary keys before the XBRL backfill: `fund_metrics(as_of,symbol,metric,engine_version)`, `dossiers(run_id)` with STORED+REJECTED runs coexisting and a `dossiers_current` view, `dossier_claims(run_id,claim_id)`; `init_schema` reconcile drops+recreates an empty wrong-PK table and refuses a non-empty one.
- **W1.2** Impact coefficient pinned at 50 bps; `rf_annual` from `EQR_RISK_FREE_PCT`.
- **W1.3** Append-only trial ledger (`experiments/trials-*.jsonl`); deflated Sharpe uses grid + prior distinct trials.
- **W1.6** Enforceable quality gate (BLOCKER/WARN) on backtest/validate/rank with `--force`.
- **W1.5** Point-in-time pack contract + request-bound dossier validation.
- **W1.7** Prospective forward ledger; L-v1 freeze 2026-09-30.
- **W1.1** Claim-state ladder (DIAGNOSTIC → PROVISIONAL → BACKTEST_PASS → PROSPECTIVE_VALIDATED) across every surface; Sleeve L is PROVISIONAL (holdout inspected + five other verified integrity items), not VALIDATED.

## Doctrine

1. Trust before depth before elegance.
2. Anchors over consensus (every score clears something that can't argue back).
3. Two engine generations, one switch (Wave 1 changes no numbers; Wave 2 changes them once with attribution).
4. The prospective clock starts now.
5. LLM output never moves a deterministic rating.
6. Any money-weighted return is XIRR-engine certified; CAGR is labelled time-weighted.

## The comprehensive scoring mechanism (Waves 3–4, designed not yet built)

Three layers + a ladder: (1) Security Rating Score per name — score/confidence/eligibility, coverage shrinks to the industry-median prior (never renormalise), Piotroski as f_score/f_known, gates cap the notch not the score, provenance stamp, calibration bar with a coverage-neutrality anchor; (2) Analyst Scorecard (M1–M12) scoring the bot not the stock, from the rating/prospective ledgers; (3) Dossier Quality Score (DQS) — deterministic verifier output, PUBLISH iff DQS≥70 ∧ verified≥.75 ∧ injection=1 ∧ ≥5 verified claims. The ladder: DIAGNOSTIC → PROVISIONAL → BACKTEST_PASS → PROSPECTIVE_VALIDATED (≥100 matured rows, ≥20/tier, ≥12 sealed months).

## Waves

- **Wave 1 (SHIPPED)** — honest labels, provenance, PIT contracts, quality gate, prospective ledger opened. No numbers changed.
- **Wave 2** — spine repair → L-v2 (split-invariant mcap via face-value history, Piotroski ratio, truth lanes, real NIFTY 500 TRI, dated rf, historical-controls policy, ISIN instrument_as_of, nested folds + CIs, one revalidation with attribution). Numbers change once.
- **Wave 3** — ×10 depth → Layer 1 rating engine (r1) + Layer 2 analyst scorecard, calibration.
- **Wave 4** — dossiers → Layer 3 verifier + DQS + adversarial eval set.
- **Wave 5** — ops (risk-weighted CI, health/Telegram on transitions, backup rehearsal, security at R6).
- **Wave B** — the prospective clock, running from Wave 1 for 12 wall-clock months.

## Governance / open decisions for Sumaer

Prospective freeze date (proposed 2026-09-30); TRI ingest vs. labelled proxy; the Upstox advisor line earns 0 points from Sleeve L until BACKTEST_PASS; `ANTHROPIC_API_KEY` unset blocks Wave 4 live smoke; parked Mac-deploy commit `06e35a1` needs a grant. Sequencing rule: W1.4 schema keys land on the live DB before any `eqr xbrl` backfill (DONE 2026-09-14). Push awaits Sumaer's explicit go.
