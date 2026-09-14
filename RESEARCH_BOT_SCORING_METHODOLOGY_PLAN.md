# 🏛️ Research Bot: Institutional Fundamental Scoring & Methodology Implementation Plan

**Status:** approved 2026-09-14 (IST); implementation started the same day (Wave 3, Layer 1). **Project:** `Downloads/Sumaer's Claude Data/Project Research Bot`, package `eqr`. **Scope:** the deterministic rating + decision layer (Wave 3, Layer 1 of the Final Plan). **Supersedes:** §3.5 (pillar table, notch map) of `docs/superpowers/plans/2026-09-14-fundamentals-x10-plan.md`. **Keeps:** every ×10 table, the `Metric` framework, the ledger, the calibration bar, the manifest, the layering rule. **Does not touch:** Sleeve L/S numbers (L-v1 prospective freeze 2026-09-30), the order path, the Upstox advisor gate semantics.

Doctrine carried in from the Final Plan: (1) gates cap the notch, never the score; (2) UNKNOWN shrinks to the prior and lowers confidence, never zero-fills, never renormalises; (3) no LLM in the compute path of any number; (4) every published rating carries its claim state; (5) money-weighted returns are XIRR-engine certified before they are quoted.

---

## 1. Executive Summary & Audit of Current State

### 1.1 What exists (verified in code, 2026-09-14)

| Layer | File(s) | What it does today | Verdict |
|---|---|---|---|
| Fundamental features | `eqr/features/fundamental.py` (`fundamental_features`, `_piotroski`, `_altman`) | 30 metrics from screener.in aggregates: TTM sales/PAT/OPM, YoY, 3y CAGR, ROE, ROCE (screener's `roce_pct`), D/E, interest cover, Sloan accruals, FCF, 7-signal Piotroski, Altman Z'' (approximated WC = other_assets − other_liabilities), P/E, P/B, P/S, EY, FCF yield, div yield, promoter/institutional 1y change | Sound as sleeve inputs. Not a research battery: no ROIC, no WACC, no cash, no receivables/inventory, no capex, no gross margin, no Beneish, no fair value |
| Cross-section | `eqr/features/xsection.py` (`winsorise`, `zscore_grouped`, `bucket_scores`, `BUCKETS`) | MAD winsorise → industry z (≥ 8 names) else universe → 4 bucket means | Reusable. Note `opm_chg_1y` sits in `z_quality` (a momentum-of-fundamentals item inside "quality") |
| Ranking | `eqr/strategy/sleeves.py` (`score_L`, `eligible`, `select`), `rank.py` (`rank_sleeve`, `validated_config`) | Fixed-weight composite, renormalised over known buckets, top-30 with rank hysteresis, inverse-vol weights, regime exposure | A portfolio constructor, not a security-level judgement. No verdict, no conviction, no valuation anchor |
| Research | `eqr/research/dossier.py`, `schema.json`, `schema.py`, `pack.py` | One Claude call over a PIT pack; strict JSON schema; citation rule; all-or-nothing storage | Good provenance discipline. But the model writes `rating` and `confidence` itself; `assessments` are four 1–5 grades with no formula; `dossiers` = 0 rows |
| Advisor surface | `eqr/surfaces/queries.py::advisor_evidence`, `advisor_client.py` | Rank percentile → points; flags (ASM, GSM, FO_BAN, ALTMAN_DISTRESS, PROMOTER_SELLING, STALE_STATEMENTS) zero points, never gate | Correct fail-soft design; no rating block yet |
| ×10 scaffolding (landed) | `eqr/store/schema.sql` (`fund_metrics`, `ratings`, `rating_ledger`, `rating_calibrations`, `statements_xbrl`, `credit_ratings`, `pledges`, `insider_trades`, `holders_named`, `doc_sections`, …), `eqr/spine/xbrl.py` | Tables created (0 rows); XBRL parser with canonical map for inventories, receivables, cash, current assets, gross block, CWIP, goodwill, CFO/CFI/CFF, auditor name and opinion, bank KPIs (CET1, CAR, GNPA/NNPA %, ROA, advances, deposits, provisions, interest earned) | The forensic pillar's raw material is one backfill away |
| Validation | `eqr/validate/*` (walk-forward, deflated Sharpe, trial ledger, claim ladder, prospective ledger, quality gate) | Pre-registered, embargoed, ledgered | Reused as-is for the rating calibration |

### 1.2 Strengths to preserve

- Point-in-time law on every fact (`visible_from` from filing dates), PIT readers in `eqr/store/pit.py`, PIT tests in `tests/test_features.py`.
- Never-zero-fill discipline (`Metric.status ∈ {OK, UNKNOWN, NA}` in the ×10 design; NaN in features today).
- Provenance: citation grammar, request-bound dossier validation, manifest sha, trial ledger, claim ladder.
- Honest validation: embargoed folds, one-shot holdout, deflated Sharpe, integrity items that keep Sleeve L at PROVISIONAL.

### 1.3 Gaps versus institutional research (what this plan closes)

1. **No economic-spread concept.** ROCE is screener's number; there is no ROIC, no WACC, so no ROIC − WACC spread, no trend, no "value creator vs destroyer" anchor.
2. **No absolute valuation.** Value is a relative z-score of yields and multiples. There is no fair value, no reverse DCF, no margin of safety, so the system cannot say "great company, wrong price".
3. **Forensic battery is one ratio.** Sloan accruals only. No Beneish M-Score, no cash-conversion history, no capitalisation checks, no other-income dependence, no receivables/inventory build.
4. **Balance-sheet view is thin.** D/E and interest cover on TTM; Altman Z'' with proxies. No net debt/EBITDA, no net debt/FCF, no cash, no maturity profile, no liquidity buffer.
5. **Growth is descriptive, not diagnostic.** CAGR and YoY only. No reinvestment rate × incremental ROIC (fundamental growth), no growth gap versus what the price implies.
6. **No management/capital-allocation record.** Promoter change and pledge flags exist; no sources-and-uses of cash over 5 years, no ROIIC, no dilution, no payout discipline, no auditor events.
7. **One weight set for every sector.** Banks are handled by NaN-ing D/E, accruals, FCF, Altman. No bank/NBFC/IT/Pharma/Manufacturing/Cyclical profiles, no NIM/NPA/CET1 components, even though screener already carries `gross_npa_pct`, `net_npa_pct` and `financing_margin_pct` for banks.
8. **Score and confidence are conflated.** A name with 3 of 8 quality inputs known gets the same kind of z as a fully covered name. The ×10 design separates them; this plan makes the Data Confidence Index a first-class output that moves conviction.
9. **No red-flag override.** Advisor flags zero points; nothing caps a verdict. There is no "SELL regardless of score" path for forensic, solvency or governance breaches.
10. **The verdict comes from the LLM.** `dossier.rating` is model prose; the deterministic engine designed in ×10 has not been built.

Data facts that shape sequencing (live DB, read-only, 2026-09-14):

- `statements_xbrl` is empty (the FY2018→ backfill has not run); `features` has 98,186 rows over 117 month-ends from 2017. Engine **r1** therefore runs and calibrates on screener + features + shareholding now; **r2** switches on XBRL-only components (cash, receivables, current liabilities, capex, gross margin, full Beneish) once the backfill lands.
- Screener gives more than `features/fundamental.py` reads today. Live `statements` line items: `pl_a/pl_q` also carry `tax_pct`, `profit_before_tax`, `opm_pct`, `expenses`, `financing_margin_pct`, and for banks `gross_npa_pct`, `net_npa_pct` (quarterly); `ratios_a` carries `inventory_days`, `days_payable`, `cash_conversion_cycle`, `roe_pct`; `cf_a` carries `cash_from_financing_activity`, `net_cash_flow`. So cash tax rate, inventory-day deltas, payable days, the full sources-and-uses table and bank NPA ratios are **r1** items. `fundamentals/base.py` reads `statements` directly, not through `Q_ITEMS/A_ITEMS`. Screener does **not** give cash, capex, cost of goods, receivables (only `debtor_days`), current assets or current liabilities. 134 symbols carry `borrowing` (singular) instead of `borrowings`: the loader coalesces both.
- Event data is thin: `announcements` covers one symbol (3,319 rows), `surveillance` has two dates (2026-09-11/14), `fo_ban` one day, `pledges`/`credit_ratings`/`insider_trades`/`dossiers` are empty. Every event-driven flag is therefore **forward-only** (cannot be calibrated over 2017→); this is the open integrity item `CONTROLS_NO_HISTORY` in `eqr/validate/claims.py`, and it keeps r1 at PROVISIONAL at best.
- `instruments.industry` is the NSE vocabulary (73 strings: `Banks`, `Finance`, `Financial Services`, `IT - Software`, `Pharmaceuticals & Biotechnology`, `Metals & Mining`, `Cement & Cement Products`, `Oil Gas & Consumable Fuels`, …). Only 39 symbols carry `deposits`; bank detection must come from industry first.
- Market cap in `features` is not split-invariant (`MCAP_NOT_SPLIT_INVARIANT`, `claims.py`): raw close × current shares. Own-history valuation bands need a corrected series (§5.2 R0.2).

---

## 2. World-Class Fundamental Research Methodology Framework

Conventions. All money in INR crore. `t` = statutory tax proxy 25% (`EQR_TAX_RATE_PCT`, default 25). "5y" means the last five fiscal years visible as of the rating date. Every metric is a `Metric(name, value|None, status, unit, source_table, source_keys, inputs_as_of, note)` (×10 T2.1). A metric whose inputs are missing is UNKNOWN; a metric that does not apply to the sector profile is NA. Percentile scoring is within the **sector profile group** (≥ 8 names) else universe, reusing `features/xsection.py::winsorise` and the ×10 `percentile_grouped`. Absolute maps are piecewise-linear and stated per component so a whole sector that destroys value cannot score well by being "relatively" good.

### Pillar 1 — Economic Moat & Business Quality

Goal: is this a value creator with pricing power that persists?

| Metric | Formula | Source (r1 → r2) | Scoring |
|---|---|---|---|
| `roic_ttm` | NOPAT / IC; NOPAT = EBIT_op × (1 − t); **EBIT_op = operating_profit − depreciation (other income excluded: treasury income is not operating)**; IC = equity_capital + reserves + borrowings − non-operating assets; non-operating assets = cash + investments (r2) or `investments` alone in r1 (note `nonop_investments_proxy`; consolidated basis first, so strategic stakes are mostly consolidated away) | screener → XBRL `cash` | input to spread |
| `wacc` | E/(D+E)·Ke + D/(D+E)·Kd·(1−t); Ke = rf + β·ERP; β = 0.67·clip(beta_250, 0.6, 1.6) + 0.33·1.0 (Blume shrink); Kd = interest / avg borrowings, clipped [rf, rf+8%]; E = mcap, D = borrowings; **floor `wacc ≥ g_T + 3%`** (recorded as `wacc_floored`) so DCF/EPV terminal values stay finite | `features.beta_250`, `EQR_RISK_FREE_PCT`, `EQR_ERP_PCT` (Damodaran India, Jan) | input to spread |
| `spread_ttm` | roic_ttm − wacc | derived | absolute map: ≤ −5% → 0 · 0 → 40 · +5 → 65 · +10 → 80 · ≥ +20 → 100 |
| `spread_median_5y` | median of yearly (ROIC_y − WACC_y) with WACC_y at that year's rf (dated rf, Wave 2) or current rf (flag `rf_undated`) | derived | same map (weight 2) |
| `spread_trend_5y` | slope of yearly spread (pp/yr) | derived | absolute: ≤ −3 → 0 · 0 → 50 · ≥ +3 → 100 |
| `roce_median_10y`, `roce_min_10y` | screener `roce_pct` | screener | pct |
| `opm_median_8y`, `opm_cv_8y` | mean/σ of yearly OPM | screener | pct (cv sign −) |
| `gross_margin_median_5y`, `gm_stability_5y` | (revenue − COGS)/revenue; COGS = cost of materials + purchases + Δinventories | XBRL only (add `CostOfMaterialsConsumed`, `PurchasesOfStockInTrade`, `ChangesInInventories…` to `xbrl.py` canonical map) | r2, pct |
| `pricing_power_proxy` | OPM change in the two years sales growth was lowest (held margin in a downturn = pricing power) | screener | absolute: ≤ −300 bp → 0 · 0 → 60 · ≥ +100 bp → 100 |
| `moat_persistence` | share of last 10 years with ROCE > WACC | derived | absolute: 0 → 0 · 0.5 → 40 · 0.8 → 75 · 1.0 → 100 |
| `moat_grade_llm` (r3, `with_qual` variant only) | verified dossier grade for moat/switching costs/network effects, 1–5 → 0–100 | `dossier_claims` verified ≥ 3 | capped at 20% of the pillar weight |

BANK substitution: franchise = ROA (XBRL `roa` or PAT/avg total_assets), ROE − CoE spread (CoE = rf + β·ERP), NIM = screener `financing_margin_pct` (r1) or (interest_earned − interest)/avg total_assets (XBRL), cost-to-income = (expenses − interest)/(financing_profit + other_income), CASA and fee income UNKNOWN until XBRL tags are mapped. NBFC substitution: ROA, ROE − CoE, `financing_margin_pct`, leverage (borrowings / BVE, absolute map 4× → 100 · 7× → 50 · ≥ 10× → 0), GNPA/NNPA from screener `pl_q` where filed. IT services: ROIC on ex-cash IC, OPM stability, cash-adjusted ROCE. Pharma: same as general plus `rnd_intensity` UNKNOWN (doc extractor later).

### Pillar 2 — Balance Sheet Fortification & Solvency

| Metric | Formula | Source | Scoring |
|---|---|---|---|
| `net_debt_ebitda` | net_debt / EBITDA; EBITDA = operating_profit (TTM); **net_debt = borrowings − cash − investments (r2) or borrowings − investments (r1, note `net_debt_investments_proxy`)**; the same `net_debt` feeds EV in Pillar 6 | screener → XBRL | absolute: ≤ 0 → 100 · 1 → 85 · 2 → 65 · 3 → 45 · 4 → 25 · ≥ 6 → 0 |
| `net_debt_fcf_years` | net_debt / median FCF 3y (NA when FCF ≤ 0 and net debt > 0 → score 0) | screener `free_cash_flow` | absolute: ≤ 0 → 100 · 3 → 70 · 6 → 40 · ≥ 10 → 0 |
| `int_cover_ttm`, `int_cover_min_5y` | EBIT / interest | screener | absolute: ≤ 1 → 0 · 2 → 30 · 4 → 60 · 8 → 85 · ≥ 15 → 100 |
| `altman_zpp` | 3.25 + 6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT/TA + 1.05·BVE/TL (existing `_altman`; WC from XBRL current assets − current liabilities in r2) | screener → XBRL | absolute: ≤ 1.1 → 0 · 1.1–2.6 grey → 40 · ≥ 2.6 → 80 · ≥ 5 → 100 |
| `current_ratio` | current_assets / current_liabilities | XBRL | r2, absolute: < 1 → 20 · 1.5 → 70 · ≥ 2 → 100 |
| `cash_to_debt`, `cash_to_mcap` | cash / borrowings; cash / mcap | XBRL | r2, pct |
| `st_debt_share` | borrowings_current / borrowings (maturity profile proxy) | XBRL | r2, absolute: ≥ 0.8 → 20 · 0.5 → 60 · ≤ 0.2 → 100 |
| `wc_days`, `wc_days_delta_3y` | screener `working_capital_days`; delta vs 3y ago | screener | pct (delta sign −) |
| `debt_equity`, `de_trend_3y` | borrowings / BVE; slope | screener | absolute + trend |
| `contingent_to_networth` | contingent liabilities / BVE | `doc_sections` extractor (×10 T4.3) | r3, absolute: ≤ 0.1 → 100 · 0.5 → 50 · ≥ 1 → 0 |

BANK substitution: capital = CET1 (absolute: < 8% → 0 · 10% → 40 · 13% → 75 · ≥ 16% → 100), CAR (XBRL, r2); asset quality = GNPA % (absolute: ≥ 8 → 0 · 4 → 40 · 2 → 75 · ≤ 1 → 100), NNPA %, GNPA trend 4q (screener `pl_q` `gross_npa_pct`/`net_npa_pct`, **r1**), provision coverage = provisions/GNPA (XBRL, r2); liquidity = deposits growth vs advances growth (screener `deposits`, XBRL `advances`). NBFC substitution: leverage (borrowings / BVE), GNPA/NNPA where filed, borrowing cost = interest / avg borrowings vs peers (funding-cost anchor), interest cover NA. Neither profile receives Altman, Beneish, net debt/EBITDA or FCF components.

### Pillar 3 — Earnings Quality & Forensic Accounting

| Metric | Formula | Source | Scoring |
|---|---|---|---|
| `cfo_to_pat_5y` | Σ CFO / Σ PAT over 5y (operating cash backing profit) | screener `cash_from_operating_activity` | absolute: ≤ 0.5 → 0 · 0.8 → 50 · 1.0 → 80 · ≥ 1.2 → 100 |
| `fcf_conversion_5y` | Σ FCF / Σ PAT over 5y | screener | absolute: ≤ 0 → 0 · 0.4 → 40 · 0.7 → 75 · ≥ 1.0 → 100 |
| `cfo_to_ebitda_5y` | Σ CFO / Σ EBITDA | screener | pct |
| `accrual_ratio_sloan` | (PAT − CFO) / avg total_assets (existing `accruals`) | screener | absolute on |x|: ≤ 2% → 100 · 5% → 60 · 10% → 20 · ≥ 15% → 0 |
| `accrual_ratio_bs` | ΔNOA / avg NOA; NOA = (TA − cash) − (TL − borrowings) | XBRL (r2) | same map |
| `beneish_m` | −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI (port of `upx/fundamentals.py`, hand-verified) | r1: DSRI (debtor_days × sales), SGI, DEPI (dep/(dep+fixed_assets)), LVGI, TATA are real; GMI (OPM proxy) and AQI (1 − (other_assets+fixed_assets)/TA) are **proxies**; SGAI UNKNOWN. **Rule: compute when ≥ 6 components are present counting at most 2 proxies (so r1 = 5 real + 2 proxies = 7 → computed, `beneish_proxies=2` recorded and the DCI source factor applies); abstain otherwise.** r2: receivables, inventories, current assets, gross block from XBRL → 7 real + SGAI UNKNOWN | level map: M < −2.22 clean → 100 · −2.22 to −1.78 watch → 50 · > −1.78 flag → 0 (weight 2) |
| `other_income_share` | other_income / PBT (TTM) | screener | absolute: ≤ 10% → 100 · 25% → 50 · ≥ 50% → 0 |
| `cash_tax_rate` | screener `tax_pct` (r1) vs statutory 25%; persistent gap > 10 pp for 3 FYs flagged | screener `tax_pct` → XBRL `tax`/`pbt` | absolute band around 25% |
| `capitalisation_proxy` | CWIP / gross_block and Δ(fixed_assets + cwip) vs capex from CFI | screener/XBRL | pct (sign −) |
| `receivable_days_delta_3y`, `inventory_days_delta_3y`, `payable_days_delta_3y`, `ccc_delta_3y` | screener `debtor_days`, `inventory_days`, `days_payable`, `cash_conversion_cycle` (all r1) | screener | absolute: ≤ −10d → 100 · 0 → 70 · +20d → 30 · ≥ +40d → 0 (payables sign reversed: stretching payables is a warning) |
| `depreciation_rate_cv_5y` | σ/mean of dep/gross_block (policy games) | screener | pct (sign −) |
| `reserves_leakage_5y` | (Σ retained PAT − Δreserves) / Σ retained PAT | screener | absolute: ≤ 5% → 100 · 15% → 50 · ≥ 30% → 0 |
| `audit_opinion_modified`, `auditor_change_24m`, `auditor_resigned_12m` | XBRL `auditor_opinion`, `auditor_name` history; announcements keyword | XBRL, announcements | binary 0/100 and red-flag inputs |
| `rpt_scale`, `contingent_liab` | doc extractors | r3 |

BANK/NBFC_FIN substitution: credit cost = provisions / avg advances (XBRL, r2); provisioning adequacy = PCR level and Δ (r2); GNPA/NNPA trend (screener `pl_q`, r1); restructured book UNKNOWN; other-income share; `beneish`, Sloan, FCF conversion NA.

### Pillar 4 — Reinvestment Runway & Growth Velocity

| Metric | Formula | Source | Scoring |
|---|---|---|---|
| `reinvestment_rate_5y` | Σ(capex − depreciation + ΔWC) / Σ NOPAT; capex = −CFI (r1 proxy, flagged `capex_from_cfi`) → XBRL purchase of PPE | screener → XBRL | absolute (higher not always better): map on 0–1 with peak at 0.4–0.8 → 100, 0 → 40, > 1.2 → 40 |
| `incremental_roic_5y` | (NOPAT_t − NOPAT_t−5) / (IC_t − IC_t−5); NA when ΔIC ≤ 0 (report `roiic_na_shrinking_ic`) | screener | absolute: ≤ 0 → 0 · WACC → 40 · 2×WACC → 75 · ≥ 30% → 100 |
| `fundamental_growth` | reinvestment_rate × incremental_roic (Damodaran sustainable growth) | derived | pct |
| `growth_gap` | implied_growth (Pillar 6 reverse DCF) − fundamental_growth | derived | absolute: ≤ −5 pp → 100 · 0 → 60 · +5 → 30 · ≥ +10 → 0 |
| `sales_cagr_3y`, `sales_cagr_5y`, `pat_cagr_5y`, `eps_cagr_5y` | existing + 5y | screener | pct |
| `growth_consistency_5y` | share of years with sales growth > 0 and PAT growth > 0 | screener | absolute: 0.4 → 20 · 0.8 → 70 · 1.0 → 100 |
| `sales_yoy_ttm`, `pat_yoy_ttm` | existing | screener | pct |
| `volume_vs_price_split` | UNKNOWN unless segment volume disclosed | dossier v2 field (r3) | informational |
| `tam_headroom_llm` (r3, `with_qual` variant only) | verified dossier grade | `dossier_claims` | capped at 20% of pillar weight |

BANK/NBFC: advances CAGR 3y, deposits CAGR 3y (banks), PPOP growth, book value per share CAGR 5y; reinvestment and ROIIC are NA.

### Pillar 5 — Management Governance & Capital Allocation

| Metric | Formula | Source | Scoring |
|---|---|---|---|
| `sources_uses_5y` | table: CFO, CFI (capex + M&A + investments), CFF (`cash_from_financing_activity`: net borrowing, dividends, buybacks, equity raised), `net_cash_flow`; splits: dividends = payout% × PAT, buybacks = Δequity_capital < 0 at constant face value, equity raised = Δequity_capital > 0, net borrowing = Δborrowings; residual CFF is labelled "other financing" | screener `cf_a` (all r1) | informational, feeds the one-pager; `cfo_minus_cfi_minus_dividends` = self-funding test (absolute: < 0 for 3 of 5 years → 20) |
| `roiic_5y` | = `incremental_roic_5y` (shared) | derived | absolute (as above) |
| `capex_return_test` | Δ EBIT 5y / Σ capex 5y | screener | absolute: ≤ 0 → 0 · 0.1 → 40 · 0.2 → 70 · ≥ 0.3 → 100 |
| `dilution_5y` | shares CAGR (equity_capital / face_value, face-value history from `corporate_actions`) | screener + corp actions | absolute: ≥ +5%/yr → 0 · 0 → 70 · buyback (< 0) → 100 |
| `payout_discipline` | dividend paid in ≥ 4 of 5 years and payout 20–60% of PAT (excess cash with no payout scores low for mature names) | screener | absolute map |
| `promoter_pct`, `promoter_chg_1y`, `promoter_chg_3y` | existing + 3y; a promoter sale matched by a bulk/block `deals` row of kind OFS within 30 days is tagged `ofs_matched` (not penalised) | shareholding, `deals` | absolute: pct ≥ 50 → 100 · 35 → 70 · 20 → 40 · < 10 → 20; change map ± |
| `pledged_pct_of_promoter`, `pledge_delta_4q` | SHP XBRL | `pledges` (empty today; forward-only from the ×10 filings sweep) | level map: 0 → 100 · ≤ 10 → 80 · ≤ 25 → 50 · ≤ 50 → 20 · > 50 → 0 (weight 2); UNKNOWN → prior until populated |
| `insider_net_buy_12m` | Σ(buys − sells) value / mcap | `insider_trades` (forward-only ledger) | absolute: ≤ −0.5% → 20 · 0 → 60 · ≥ +0.5% → 100 |
| `inst_chg_1y` | existing | shareholding | pct |
| `rating_migration_12m`, `outlook_negative` | notches | `credit_ratings` (forward-only, from ~Sep 2023) | absolute; binary |
| `adverse_events_90d` | keyword table (SEBI order, fraud, default, resignation of auditor/CFO, USFDA warning letter / OAI / import alert for pharma) | announcements (one symbol today; universe sweep is ×10 T1.5/T6) | binary 0/100; UNKNOWN → prior |
| `exec_comp_to_pat`, `board_independence`, `rpt_scale` | doc extractors | r3 |
| `mgmt_grade_llm` (r3, `with_qual` variant only) | verified dossier grades (capital allocation, disclosure, promise-vs-delivery) | `dossier_claims` | capped at 20% of pillar weight; see §3.2 on the `with_qual` variant |

### Pillar 6 — Multi-Valuation Engine & Margin of Safety

Six models, each producing a fair value per share where its inputs exist. Fair value (FV) = weight-median of available model FVs with sector-profile weights; MoS = FV / price − 1. Model dispersion feeds the Data Confidence Index.

| Model | Formula | Inputs | Profiles |
|---|---|---|---|
| **Reverse DCF** (diagnostic, not a FV) | solve g such that PV(FCFF_0·(1+g)^n, n=1..10, WACC) + TV(g_T = 5%) = EV; `implied_growth` = g; `growth_gap` = g − fundamental_growth | FCFF_0 = median FCF 3y (or NOPAT − reinvestment), EV = mcap + borrowings − cash | all non-fin |
| **Two-stage FCFF DCF** (base / bull / bear) | stage 1 (5y) g = clip(fundamental_growth, −5%, 25%) ±5 pp scenarios; stage 2 fade to g_T = 5% over 5y; TV at WACC − g_T; equity = EV − net debt; per share | as above | GENERAL, CYCLICAL (mid-cycle FCFF), IT, PHARMA |
| **Normalised EV/EBITDA** | FV = (median own 10y EV/EBITDA band, clipped to sector p25–p75) × normalised EBITDA (5y median margin × TTM sales) − net debt | screener EBITDA history, `features.mcap_cr` | all non-fin; primary for CYCLICAL |
| **P/FCF** | FV = own 10y median P/FCF × median FCF 3y per share | screener | GENERAL, IT |
| **Earnings power value (EPV)** | FV = NOPAT_normalised / WACC − net debt (no-growth floor) | screener | all non-fin; used as the bear anchor |
| **Justified P/B / DDM** | P/B* = (ROE − g)/(CoE − g), g = retention × ROE clipped ≤ CoE − 1%; FV = P/B* × BVPS; DDM (Gordon) when payout ≥ 30% | screener ROE, payout, BVE | BANK / NBFC_FIN primary; dividend payers |
| **Relative bands** (pillar score only) | P/E, EV/EBIT position in own 10y band (0 = cheapest); EY, FCF yield, div yield percentiles vs profile group | screener | all |

Pillar 6 score components: `pe_band_pos_10y` (−), `ev_ebitda_band_pos` (−), `earnings_yield` (+), `fcf_yield` (+), `div_yield` (+), `growth_gap` (−), `mos_base` (absolute: ≤ −40% → 0 · −20 → 20 · 0 → 50 · +20 → 75 · ≥ +50% → 100), `pb_vs_justified` (BANK / NBFC_FIN, −). Rationale for keeping valuation inside the score **and** MoS as a separate decision axis: the pillar measures relative cheapness against peers and own history, MoS measures absolute value; the calibration (§6) runs a `no_valuation_pillar` variant to measure the double-count and the plan accepts the smaller-IC variant if the difference is inside noise.

Expected-return band (informational only, never a score input): `er_mid = earnings_yield + clip(fundamental_growth, −10%, 20%) + clip(ln(pe_median_10y / pe_ttm)/3, ±15%)`, `± max(10%, vol_250/√3)`.

---

## 3. World-Class Composite Scoring Engine Architecture

### 3.1 Data model (pure Python, no I/O in the engine)

```python
# eqr/rating/model.py
class Status(str, Enum): OK="OK"; UNKNOWN="UNKNOWN"; NA="NA"

@dataclass(frozen=True)
class Component:
    name: str; pillar: str; kind: Literal["pct","map","binary","level"]
    sign: int = +1; weight: float = 1.0
    map_points: tuple[tuple[float,float],...] | None = None   # (x, score) piecewise-linear
    profiles: frozenset[str] = frozenset({"ALL"})              # which sector profiles use it
    engine_min: str = "r1"                                     # r1 | r2 | r3

@dataclass
class ComponentScore:
    name: str; raw: float | None; score: float | None; status: Status
    weight: float; provenance: str; shrunk_to_prior: bool

@dataclass
class PillarScore:
    name: str; score: float | None; status: Status
    weight_known: float; weight_total: float; components: list[ComponentScore]

@dataclass
class RedFlag:
    code: str; tier: Literal["HARD","SOFT"]; cap: str      # cap = max notch allowed
    evidence: str; source: str; value: float | None

@dataclass
class Valuation:
    price: float; fv_base: float | None; fv_bull: float | None; fv_bear: float | None
    mos_base: float | None; implied_growth: float | None; fundamental_growth: float | None
    models: dict[str, float | None]; dispersion: float | None; wacc: float | None

@dataclass
class Confidence:
    dci: float; band: Literal["HIGH","MED","LOW"]
    component_coverage: float; pillar_coverage: float; staleness_factor: float
    source_factor: float; valuation_dispersion_factor: float; flags: list[str]

@dataclass
class Decision:
    verdict: Literal["CONVICTION_BUY","SPECULATIVE_BUY","HOLD","TRIM","SELL","NO_RATING"]
    rule_id: str; reason: str; conviction: Literal["HIGH","MED","LOW"]
    downgraded_by_confidence: bool

@dataclass
class RatingResult:
    symbol: str; as_of: date; engine_version: str; variant: str; profile: str
    score: float | None; pillars: dict[str, PillarScore]; red_flags: list[RedFlag]
    valuation: Valuation; confidence: Confidence; decision: Decision
    status: Literal["RATED","NO_RATING"]; data_errors: list[str]
    manifest: dict; manifest_sha: str
    def to_row(self) -> dict: ...        # → ratings table (pillars_json, gates_json=red_flags, manifest_json, …)
```

### 3.2 Pillar weighting system

Sector profile is resolved once per symbol by `eqr/rating/sector.py::profile_for(industry, is_bank, statements)` against the **actual 73 NSE industry strings in `instruments.industry`** (live list read 2026-09-14). `SECTOR_PROFILE_MAP` is an explicit dict over all 73 strings; a test asserts every live industry is mapped, and a new unmapped string fails loudly (`profile_unmapped` → NO_RATING cause), never silently GENERAL.

| Profile | NSE industry strings (exact) | Extra rule |
|---|---|---|
| BANK | `Banks` | also any name with `deposits` in `bs_a` and XBRL bank markers |
| NBFC_FIN | `Finance`, `Financial Services`, `Financial Technology (Fintech)`, `Capital Markets`, `Insurance` | Insurance carries note `insurance_metrics_partial` (no embedded-value data) |
| IT_SERVICES | `IT - Software`, `IT - Services`, `Information Technology` | `IT - Hardware` → GENERAL |
| PHARMA | `Pharmaceuticals & Biotechnology`, `Healthcare`, `Healthcare Services`, `Healthcare Equipment & Supplies` | USFDA keyword flags apply |
| CYCLICAL | `Metals & Mining`, `Ferrous Metals`, `Non - Ferrous Metals`, `Diversified Metals`, `Minerals & Mining`, `Metals & Minerals Trading`, `Cement & Cement Products`, `Construction Materials`, `Other Construction Materials`, `Oil`, `Oil Gas & Consumable Fuels`, `Petroleum Products`, `Consumable Fuels`, `Chemicals & Petrochemicals`, `Fertilizers & Agrochemicals`, `Paper, Forest & Jute Products`, `Textiles`, `Textiles & Apparels`, `Realty` | mid-cycle (5y median margin) normalisation in P6 |
| GENERAL | everything else (autos, auto components, capital goods, industrial products, electrical equipment, FMCG, consumer durables, retail, media, telecom, power, gas, utilities, transport, construction, services, chemicals (specialty), diversified) | regulated utilities (`Power`, `Gas`, `Other Utilities`, `Telecom - Services`, `Transport Infrastructure`) carry tag `regulated` (informational; no separate profile, YAGNI until calibration shows a need) |

| Pillar | GENERAL | BANK | NBFC_FIN | IT_SERVICES | PHARMA | CYCLICAL |
|---|---|---|---|---|---|---|
| P1 Moat & quality | 0.20 | 0.25 | 0.20 | 0.25 | 0.20 | 0.15 |
| P2 Balance sheet | 0.15 | 0.25 | 0.30 | 0.05 | 0.10 | 0.25 |
| P3 Earnings quality | 0.15 | 0.15 | 0.15 | 0.15 | 0.20 | 0.15 |
| P4 Growth & runway | 0.15 | 0.10 | 0.10 | 0.20 | 0.15 | 0.10 |
| P5 Management | 0.10 | 0.10 | 0.10 | 0.15 | 0.15 | 0.10 |
| P6 Valuation | 0.25 | 0.15 | 0.15 | 0.20 | 0.20 | 0.25 |

Every column sums to 1.00 (asserted in a test). Three pre-registered variants only (as in ×10): `base` (table above), `quality_tilt` (+0.05 P1, +0.05 P3, −0.10 P6), `value_tilt` (+0.10 P6, −0.05 P1, −0.05 P4). A fourth, `with_qual` (r3), is the **only** variant in which the capped LLM grades (`moat_grade_llm`, `tam_headroom_llm`, `mgmt_grade_llm`) enter a pillar; it is calibrated and labelled separately and is never the published default, which keeps the doctrine "no LLM in the compute path of the published rating" literally true. Any other weight change bumps `ENGINE_VERSION` and requires a fresh calibration. Momentum is **not** a fundamental pillar: it is emitted as a separate `timing` tag on the one-pager (`mom_12_1`, `dist_52w_high`, `dma200_ratio`) and stays the sleeves' business.

Composite:

```
prior_i    = median component score over names in the same (as_of, profile) group with ≥ 8 known values,
             else over the universe on that as_of   (pct → 50 by construction; map/binary → the group's median mapped score)
component  c_i ∈ [0,100] when known, else prior_i  (shrunk_to_prior = True)
pillar P_k = Σ w_i·c_i / Σ w_i over ALL applicable components (UNKNOWN components use the prior, never dropped)
             pillar status UNKNOWN when known weight < 50% of applicable weight → pillar = its group prior and DCI drops
Score S    = Σ_k W_k(profile, variant)·P_k / Σ_k W_k         (NA pillars are impossible by construction: every profile has all 6)
```

This is the Final Plan's "shrink to the prior, never renormalise" rule. The ×10 §3.5 text said "renormalised away"; this plan adopts the later Final Plan rule and the calibration checks coverage-neutrality (§6).

### 3.3 Red-Flag Override Engine (`eqr/rating/flags.py`)

Flags never change the score. Three tiers: **HARD** (cap = SELL), **SOFT** (cap = HOLD or TRIM), **WATCH** (no cap; blocks Conviction BUY and counts toward the "moderate risk" test). The decision engine applies `min(verdict, cap)` over HARD and SOFT flags after the score-based verdict is computed. Every fired flag is stored with evidence in `gates_json`. Availability column: `hist` = computable over 2017→ (calibratable), `fwd` = forward-only until the ×10 event feeds are populated (`CONTROLS_NO_HISTORY` integrity item; these flags are evaluated live and their precision is measured only prospectively).

**HARD flags (cap = SELL):**

| Code | Condition | Source | Avail. |
|---|---|---|---|
| `FORENSIC_BENEISH_2Y` | Beneish M > −1.78 in the last two FYs (computed under the ≥ 6-components-≤ 2-proxies rule) AND accrual_ratio_sloan > 10% in the latest FY | statements / XBRL | hist (r1 with proxies; r2 clean) |
| `FORENSIC_CASH_DIVERGENCE` | accrual_ratio_sloan > 15% in each of the last two FYs AND cfo_to_pat_5y < 0.5 (non-fin) | statements | hist |
| `SOLVENCY_BREACH` | non-fin: Altman Z'' < 1.1 AND int_cover_ttm < 1.5; or net_debt_ebitda > 6 AND int_cover < 1.0 | statements | hist |
| `CAPITAL_BREACH_BANK` | GNPA % > 10% (screener `pl_q`, hist) or CET1 < 8% (XBRL, fwd) | statements / XBRL bank | hist / fwd |
| `AUDIT_QUALIFIED_OR_RESIGNED` | modified/adverse/disclaimer opinion in the latest FY, or auditor resignation ≤ 12 months | XBRL opinion, announcements | fwd |
| `DEFAULT_EVENT` | credit rating D / default announcement ≤ 90 days | credit_ratings, announcements | fwd |
| `PLEDGE_GT_50` | pledged % of promoter holding > 50 | pledges | fwd |
| `GSM` | on the GSM list on as_of | surveillance | fwd (2 days of history) |
| `REGULATORY_FRAUD` | SEBI order naming the company/promoter for fraud, or forensic audit announced ≤ 180 days | announcements keyword table (ported from `upx/scoring.py`) | fwd |

**SOFT flags (cap as stated):**

| Code | Condition | Cap | Avail. |
|---|---|---|---|
| `BENEISH_1Y` | M > −1.78 in the latest FY only | HOLD | hist |
| `STALE_STATEMENTS` | latest statement > 200 days old | HOLD (> 400 days → NO_RATING) | hist |
| `PROMOTER_SELLING` | promoter_chg_1y ≤ −5 pp and no `ofs_matched` bulk/block deal | HOLD | hist (shareholding), deals fwd |
| `MOAT_EROSION` | spread_ttm < 0 after spread_median_5y > 5%, or OPM down > 500 bp over 3y with sales growing | HOLD | hist |
| `DEBT_SPIKE` | net_debt_ebitda rose by > 2.0 turns in 12m | HOLD | hist |
| `OTHER_INCOME_DEPENDENCE` | other_income_share > 50% for 2 FYs | HOLD | hist |
| `LEVERAGED_BUYBACK` | buyback while net_debt_ebitda > 3 | TRIM | hist |
| `PLEDGE_GT_25` | pledged 25–50% | TRIM | fwd |
| `ASM_STAGE_2_PLUS`, `FO_BAN` | surveillance / ban on as_of | HOLD | fwd |
| `RATING_DOWNGRADE_2N` | ≥ 2 notches down in 12m, or outlook negative with notch ≤ BBB | HOLD | fwd |
| `PHARMA_USFDA_OAI` | warning letter / OAI / import alert ≤ 12 months (PHARMA profile) | HOLD | fwd |

**WATCH flags (no cap; shown on the one-pager; any WATCH flag blocks Conviction BUY):** `OTHER_INCOME_25_50` (share 25–50%), `PLEDGE_10_25`, `PROMOTER_SELLING_2_5PP` (−2 to −5 pp; the advisor's existing `PROMOTER_SELLING` threshold of −2 pp maps here), `BENEISH_WATCH` (−2.22 < M ≤ −1.78), `WC_DAYS_UP_20` (working-capital days +20 in 3y), `TAX_GAP` (cash tax rate gap > 10 pp for 3 FYs), `VALUATION_DISPERSION_GT_50`, `DEBT_UP_1_TURN`.

Precedence: HARD beats SOFT; the most restrictive cap wins; `NO_RATING` (data error) beats everything.

### 3.4 Data Confidence Index (`eqr/rating/confidence.py`)

```
component_coverage = Σ w_i·[known_i] / Σ w_i           over applicable components (0..1)
pillar_coverage    = #pillars with status OK / 6
staleness          = 1.00 (≤ 120 d) · 0.85 (≤ 200 d) · 0.70 (≤ 400 d)
source             = 1.00 XBRL as-reported · 0.90 screener as-restated · ×0.85 when XBRL-vs-screener FY sales disagree > 10%
                     (the r1 Beneish with 2 proxies is covered by the screener factor; no extra penalty)
val_dispersion     = 1.00 (model FV spread ≤ 25%) · 0.85 (≤ 50%) · 0.70 (> 50% or < 2 models)
name_flags         = 0.90^n over NAME-SPECIFIC integrity items only:
                     {implausible P/E (> 200, or < 0 with PAT > 0), PAT CAGR discontinuity > 150%, history < 240 sessions, borrowing/borrowings both present with different values}
                     Universe-wide items (MCAP_NOT_SPLIT_INVARIANT, AS_RESTATED_FUNDAMENTALS, BENCH_PROXY, CONTROLS_NO_HISTORY)
                     are NOT in the DCI: they live on the claim ladder and keep the engine PROVISIONAL.

DCI = (0.45·component_coverage + 0.15·pillar_coverage + 0.40) × staleness × source × val_dispersion × name_flags
range: fully covered, fresh, screener-sourced, low-dispersion name = 1.00 × 1.00 × 0.90 × 1.00 × 1.00 = 0.90 (HIGH);
       the same name with 31% model dispersion = 0.765 (HIGH, just); with 23/27 components known = 0.90 × (0.45·0.85+0.15+0.40) = 0.84 (HIGH);
       worst case ≈ 0.11. DCI never exceeds 1.00.
band: HIGH ≥ 0.75 · MED ≥ 0.50 · LOW < 0.50 · NO_RATING when DCI < 0.35
```

Effect on conviction (§4): MED band caps at Speculative BUY (rule R5b makes an S ≥ 80, MoS ≥ 20% name with MED data a Speculative BUY, not a HOLD); LOW band downgrades any BUY one step (Conviction BUY → Speculative BUY → HOLD) and turns SELL-by-score into `SELL (low data)` with the note that the score is precautionary. HARD red flags are never softened by low confidence: an unverifiable company with a hard flag is still SELL / AVOID.

`DATA_ERROR → NO_RATING` (named causes, xirr-engine pattern): component_coverage < 0.60; P1 or P6 UNKNOWN; price history < 120 sessions; statements > 400 days; `fund_metrics` slice missing for `(as_of, symbol)`; DCI < 0.35; sector profile unresolved with is_bank ambiguous (deposits present but no bank industry).

### 3.5 Manifest and determinism

`manifest = {engine_version, variant, profile, inputs: [{metric, value, status, source_table, source_keys, inputs_as_of}], weights, maps, thresholds, flags, models, sha256}`; identical inputs → identical `manifest_sha` (tested). Stored in `ratings.manifest_json`.

---

## 4. Intuitive BUY / HOLD / SELL Decision Framework

### 4.1 Decision matrix (ordered rules, first match wins; `S` = score, `MoS` = mos_base, `DCI` band as above)

```python
# eqr/rating/decision.py
def decide(S, mos, dci_band, flags, growth_catalyst, p2) -> Decision:
    if S is None or dci_band == "NONE": return NO_RATING
    hard  = [f for f in flags if f.tier == "HARD"]
    soft  = [f for f in flags if f.tier == "SOFT"]      # each carries a cap (HOLD or TRIM)
    watch = [f for f in flags if f.tier == "WATCH"]     # no cap
    if hard:                                  return SELL   ("R1_HARD_FLAG", conviction HIGH)
    if S < 35:                                return SELL   ("R2_SCORE_LT_35")
    if mos is not None and mos <= -0.25:      return TRIM   ("R3_OVERVALUED_25")      # price beats quality
    if 35 <= S < 50:                          return TRIM   ("R4_SCORE_35_49")
    if S >= 80 and mos is not None and mos >= 0.20 and not soft and not watch and dci_band == "HIGH":
                                              return CONVICTION_BUY ("R5_CONVICTION")
    if S >= 80 and mos is not None and mos >= 0.20 and not soft and len(watch) <= 1 and dci_band in ("HIGH","MED"):
                                              return SPECULATIVE_BUY ("R5B_CONVICTION_DATA_OR_WATCH_LIMITED")
    if S >= 70 and growth_catalyst and p2 >= 40 and not soft and len(watch) <= 1 and dci_band in ("HIGH","MED") and (mos is None or mos > -0.10):
                                              return SPECULATIVE_BUY ("R6_SPECULATIVE")
    if S >= 80 and (mos is None or -0.10 <= mos < 0.20):
                                              return HOLD   ("R7_QUALITY_WAIT_FOR_PRICE")
    if 50 <= S < 70 or (mos is not None and abs(mos) <= 0.10):
                                              return HOLD   ("R8_HOLD_BAND")
    return HOLD ("R9_GOOD_BUT_NO_CATALYST")   # S ≥ 70 reaches here; S in [50,70) matched R8; S < 50 matched R2/R4
    # then: verdict = min(verdict, cap(f)) for f in soft flags; then the DCI downgrade rule (§3.4); then hysteresis
```

`growth_catalyst` is **deterministic only**: P4 ≥ 70 **and** (`fundamental_growth` ≥ 12% with `growth_gap` ≤ 0, or `pat_yoy_ttm` ≥ 20% with `sales_yoy_ttm` ≥ 10%, or `eps_cagr_5y` ≥ 15% with `growth_consistency_5y` ≥ 0.8). A verified dossier catalyst is **displayed** on the one-pager next to the deterministic test but never enters `decide()` (doctrine: LLM output never moves the published rating). "Moderate risk" = P2 ≥ 40, no SOFT flag, ≤ 1 WATCH flag. Because every SOFT flag caps at HOLD/TRIM, a BUY verdict is by construction free of SOFT flags; the "≤ 1" allowance applies to WATCH flags.

Precise conditions restated in Sumaer's terms:

| Verdict | Condition | Conviction |
|---|---|---|
| **Conviction BUY** | S ≥ 80 AND MoS ≥ 20% AND no red flags of any tier AND DCI HIGH | HIGH |
| **Speculative BUY** | (S ≥ 80 AND MoS ≥ 20% with MED data or one WATCH flag) OR (S ≥ 70 AND deterministic growth catalyst AND moderate risk (P2 ≥ 40, no SOFT, ≤ 1 WATCH) AND MoS > −10% AND DCI ≥ MED) | MED (LOW if DCI MED) |
| **HOLD** | S 50–69, OR |MoS| ≤ 10%, OR S ≥ 80 with MoS < 20% ("wait for price"), OR S ≥ 70 without a catalyst, OR a SOFT-flag cap | MED |
| **TRIM / REDUCE** | S 35–49, OR overvalued by > 25% (MoS ≤ −25%), OR pledge 25–50%, OR leveraged buyback | MED |
| **SELL / AVOID** | S < 35, OR any HARD red flag (forensic, cash divergence, solvency, bank capital, audit, default, GSM, pledge > 50%, fraud) | HIGH when hard flag; MED otherwise |
| **NO_RATING** | DATA_ERROR causes listed in §3.4 | — |

Reachability (asserted by table-driven tests): every rule R1–R9 has at least one fixture that reaches it; no fixture reaches two rules.

Verdict hysteresis (anti-churn, mirrors `select()` in sleeves): a published verdict only moves up when the new rule is satisfied by a margin (S ≥ threshold + 2, MoS ≥ threshold + 3 pp) and moves down immediately; measured as `monthly notch transition ≤ 25%` in calibration. Hysteresis makes the verdict path-dependent, so the calibration (§6.1) replays signal dates sequentially with `prev_verdict` and reports every tier statistic **both with and without** hysteresis; the raw (no-hysteresis) numbers are the ones judged against the bar.

### 4.2 Stock Decision One-Pager (layout of `eqr/surfaces/report.py` output; light theme, inline SVG, Jinja2 + the existing `md.py`)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ RELIANCE · Reliance Industries · GENERAL profile · as of 2026-09-12 · engine r1/base   │
│ Claim state: DIAGNOSTIC (r1 not yet calibrated)                                        │
├──────────────────────────────────────────────────────────────────────────────────────┤
│  ███  CONVICTION BUY  ███      Score 84 / 100      MoS +27%      Confidence HIGH (0.84) │
│  Rule R5 · no red flags · fair value ₹1,910 (bear 1,420 · base 1,910 · bull 2,350)     │
│  (DCI 0.84 = 0.90 screener source × (0.45·0.85 coverage + 0.15 + 0.40), dispersion 22%)  │
│  Price ₹1,505  ├───────●───────────┤  bear ─── base ─── bull   (FV range bar w/ price)  │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ PILLARS (bars 0–100, weight in brackets, ● = known coverage)                            │
│  Moat & quality   [.20]  ████████████████░░░░  82  ●●●●○   ROIC 17.4% vs WACC 10.1%      │
│  Balance sheet    [.15]  ██████████████░░░░░░  71  ●●●●●   ND/EBITDA 1.4x · IC 7.9x      │
│  Earnings quality [.15]  ███████████████████░  93  ●●●●○   CFO/PAT 1.12 · Beneish −2.6   │
│  Growth & runway  [.15]  ██████████████░░░░░░  68  ●●●○○   reinvest 0.62 × ROIIC 19%     │
│  Management       [.10]  ████████████████░░░░  80  ●●●●○   promoter 50.3% · 0% pledged   │
│  Valuation        [.25]  ██████████████████░░  89  ●●●●●   P/E band p18 · implied g 6%   │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ KEY MOAT DRIVERS                       │ TOP 3 RISKS                                    │
│ • ROIC−WACC spread +7.3 pp, 9/10 yrs   │ 1. Capex cycle: reinvestment 0.62 with ROIIC   │
│   positive (moat persistence 0.9)      │    falling from 24% → 19% (P4)                 │
│ • OPM held +40 bp through FY20 sales   │ 2. Other income 18% of PBT (below the 25%      │
│   decline (pricing power proxy)        │    WATCH threshold)                            │
│ • Gross margin: UNKNOWN until XBRL r2  │ 3. Net debt uses investments as the cash proxy │
│                                        │    (r1; XBRL cash pending)                     │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ RED FLAGS: none fired (HARD 0 · SOFT 0 · WATCH 0) · nearest: OTHER_INCOME_25_50 at 18%   │
│ ANALYST VIEW (dossier, does not move the rating): none stored · catalysts: none          │
│ TIMING (not in score): 12-1m momentum +14% · 8% below 52w high · above 200 DMA          │
│ WHAT WOULD CHANGE THIS: MoS < 10% (price > ₹1,740) → HOLD; ND/EBITDA > 3 → SOFT flag     │
│ DATA: screener as-restated (source 0.90) · statements 71 d old · 23/27 components known │
│ Manifest sha 3f9a… · ratings row (RELIANCE, 2026-09-12, r1, base)                       │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Surfaces: `/decision/{symbol}` (HTML), `data/reports/decision-{symbol}-{as_of}.md` (Markdown, same renderer), Telegram compact card (5 lines: verdict, score, MoS, confidence, top flag), advisor block `decision: {verdict, rule_id, score, mos, dci, band, flags, claim_state}` (fail-soft, can only zero points on a BACKTEST_PASS+ SELL, never gates), `/ratings` table sortable by verdict/score/MoS/DCI with CSV export.

---

## 5. Step-by-Step Codebase Implementation Plan

Layering (`tests/test_layering.py` does not exist yet; it is created in task R2.2 as ×10 T3.1 planned): `spine` → `store` → `features` → `strategy` never import `fundamentals`, `rating`, `research`. `rating` may import `features.xsection` and `store.pit`. `research` may import `rating` (the pack carries the engine's decision; the LLM never feeds it back). `dossiers.engine_rating` / `llm_view` exist in the schema (`migrations.sql`) but `dossier.py` does not write them today; R4.2 makes it do so.

### 5.1 File map (`[NEW]` / `[MODIFY]` / `[KEEP]`)

| File | Change |
|---|---|
| `[MODIFY] eqr/store/schema.sql` + `migrations.sql` | The verdict is written into the existing `ratings.rating` column (enum CONVICTION_BUY/SPECULATIVE_BUY/HOLD/TRIM/SELL/NO_RATING) and `ratings.confidence` holds the DCI. `ratings` gains only `rule_id VARCHAR, profile VARCHAR, mos_base DOUBLE, fv_base DOUBLE, fv_bull DOUBLE, fv_bear DOUBLE, dci_band VARCHAR, valuation_json VARCHAR, decision_json VARCHAR` (ADD COLUMN IF NOT EXISTS in `migrations.sql`, which `init_schema` already runs; PK unchanged). `rating_ledger` (PK symbol, as_of, engine_version, no variant) gains `mos_at_publish DOUBLE, dci_at_publish DOUBLE`; **only the `base` variant is ever published** to the ledger. `fund_metrics` unchanged. |
| `[NEW] eqr/fundamentals/base.py` | ×10 T2.1 as approved: `Metric`, `MetricSet`, `Inputs`, `load_inputs(con, as_of, symbols)` (reads `statements` directly, coalesces `borrowing`/`borrowings`, includes `tax_pct`, `inventory_days`, `days_payable`, `cash_conversion_cycle`, `roe_pct`, `cash_from_financing_activity`, `net_cash_flow`, `gross_npa_pct`, `net_npa_pct`, `financing_margin_pct`), `percentile_grouped`, `is_financial`. Plus **`mcap_series(con, symbol, as_of)`**: split-invariant historical market cap = `adj_close_y × (equity_capital_y / face_value_current)` using `adj_factors` (adjusted closes are on the current face-value basis) and `corporate_actions.face_value` (24,032 of 24,037 rows populated); this is what the own-history P/E, EV/EBITDA and P/FCF bands consume, so the `MCAP_NOT_SPLIT_INVARIANT` integrity item does not contaminate Pillar 6 (it still applies to `features.mcap_cr` used by the sleeves until Wave 2). |
| `[NEW] eqr/fundamentals/moat.py` | Pillar 1 metrics: `roic`, `wacc`, `spread_ttm`, `spread_median_5y`, `spread_trend_5y`, `pricing_power_proxy`, `moat_persistence`, gross-margin family (r2). |
| `[NEW] eqr/fundamentals/solvency.py` | Pillar 2: `net_debt_ebitda`, `net_debt_fcf_years`, `int_cover_min_5y`, `altman_zpp` (ported from `features/fundamental.py::_altman`, XBRL WC in r2), `current_ratio`, `st_debt_share`, `wc_days_delta_3y`, `de_trend_3y`; bank block (CET1, CAR, GNPA/NNPA, PCR, credit cost). |
| `[NEW] eqr/fundamentals/forensic.py` | Pillar 3: `beneish` (port of `upx/fundamentals.py` with the paper's 4.679 TATA coefficient; abstain < 6 real components), `sloan`, `accrual_bs`, `cfo_to_pat_5y`, `fcf_conversion_5y`, `other_income_share`, `capitalisation_proxy`, `receivable/inventory_days_delta`, `depreciation_cv`, `reserves_leakage`, audit events. |
| `[NEW] eqr/fundamentals/growth.py` | Pillar 4: `reinvestment_rate_5y`, `incremental_roic_5y`, `fundamental_growth`, CAGRs, `growth_consistency_5y`, `growth_gap` (needs valuation's implied growth: computed in `build.py` after valuation). |
| `[NEW] eqr/fundamentals/management.py` | Pillar 5: `sources_uses_5y`, `capex_return_test`, `dilution_5y`, `payout_discipline`, promoter/pledge/insider/rating/adverse-event metrics (`adverse_events(ann, as_of, days=90)` with the ported keyword table). |
| `[NEW] eqr/fundamentals/valuation.py` | Pillar 6: `wacc(beta, rf_pct, erp_pct, debt_w, kd_pct, tax)`, `implied_growth(ev, fcff0, wacc, years=10, g_terminal=0.05)` (bisection), `dcf_two_stage(fcff0, g1, wacc, g_terminal, years1=5, fade=5)`, `ev_ebitda_fv`, `p_fcf_fv`, `epv`, `justified_pb`, `ddm`, `own_band_position(series, current)`, `triangulate(models, profile_weights) -> (fv_base, fv_bull, fv_bear, dispersion)`, `expected_return_band`. |
| `[NEW] eqr/fundamentals/sector_kpis.py` | ×10 T2.6 unchanged (bank/NBFC KPIs from XBRL; others UNKNOWN). |
| `[NEW] eqr/fundamentals/build.py` | `METRICS_VERSION = "m1"`; `build_metrics(con, as_of, symbols=None, store=True)` → `fund_metrics` long rows, replaces the `(as_of, engine_version)` slice; order: base → moat → solvency → forensic → valuation → growth (growth_gap) → management. CLI `eqr metrics --as-of|--monthly-from|--symbols`. |
| `[NEW] eqr/rating/model.py` | dataclasses of §3.1. |
| `[NEW] eqr/rating/sector.py` | `SECTOR_PROFILE_MAP`, `profile_for(industry, is_bank, stmts) -> str`, `PROFILE_WEIGHTS[profile][variant]`. |
| `[NEW] eqr/rating/pillars.py` | `COMPONENTS: list[Component]` (every row of §2 tables with kind, sign, weight, map points, profiles, engine_min); `pillar_score(name, metrics, profile, variant, engine) -> PillarScore` implementing shrink-to-prior. |
| `[NEW] eqr/rating/flags.py` | `evaluate_flags(metrics, features_row, surveillance, announcements, profile) -> list[RedFlag]` (§3.3 tables as data). |
| `[NEW] eqr/rating/confidence.py` | `data_confidence(pillars, metrics, staleness_days, source, dispersion, integrity) -> Confidence` (§3.4). |
| `[NEW] eqr/rating/decision.py` | `decide(...) -> Decision` (§4.1), `apply_caps(decision, flags)`, `apply_confidence(decision, band)`, `hysteresis(prev_verdict, new, S, mos)`. |
| `[NEW] eqr/rating/engine.py` | `ENGINE_VERSION = "r1"`; `rate_symbol(symbol, as_of, metrics: MetricSet, feat_row, ctx, variant="base") -> RatingResult` (pure); `rate_universe(con, as_of, variant="base", engine=None, store=True)`; manifest builder + sha. |
| `[NEW] eqr/rating/ledger.py` | `store_ratings`, `publish(con, as_of, engine_version)` append-only, `mature(con, today)` (12m fwd adjusted return, delisting haircut 1%, benchmark from `index_series`), `latest_rating(con, symbol)`, `verdict_history(con, symbol)`. |
| `[NEW] eqr/rating/calibrate.py`, `acceptance.py`, `report.py` | ×10 T3.3 with the §6 additions (tier-level tests, MoS IC, flag precision, coverage neutrality, no-valuation variant). |
| `[MODIFY] eqr/research/schema.json` + `schema.py` | v2 (v1 stays valid): `engine_decision` echo (`{verdict, score, mos, dci}` copied from the pack, validated equal to the pack, never authored), `grades` object (moat, management, capital_allocation, disclosure, promise_vs_delivery, tam_headroom: 1–5 with ≥ 1 citation each), `catalysts[].expected_by` as ISO date, `disagreements_with_engine[]`, `volume_vs_price_note`. `TABLE_CITATIONS` += `table:fund_metrics`, `table:rating`, `table:valuation`. |
| `[MODIFY] eqr/research/pack.py` | pack v2 adds `fund_metrics` (with percentiles), `rating` row, `valuation` block, `red_flags`; token budget per ×10 T6.3. |
| `[MODIFY] eqr/research/dossier.py` | `render_markdown` v2 prints the engine decision card first, then the LLM view labelled "analyst view (does not move the rating)". `run_dossier` stores `engine_rating` and `llm_view` columns (already in `dossiers`). |
| `[NEW] eqr/surfaces/report.py` | `decision_onepager(rating: RatingResult, feat_row, dossier=None) -> str` (Markdown), `decision_html(...)` (Jinja2 template `decision.html`), `pillar_bars_svg`, `fv_range_svg`, `telegram_card(rating) -> str`. |
| `[MODIFY] eqr/surfaces/queries.py`, `web/app.py`, `digest.py`, `advisor_client.py` | routes `/decision/{symbol}`, `/ratings`; `advisor_evidence` gains a `decision` block `{verdict, rule_id, score, mos, dci, band, flags, claim_state}`; digest lines for verdict changes and new flags on held names. **Advisor semantics, stated as an intentional change:** today `evidence_line` zeroes points on any flag and `PROMOTER_SELLING` fires at −2 pp; after this plan the existing sleeve-based `flags` behaviour is unchanged (−2 pp stays, mapped to the WATCH tier), and the new `decision` block can zero points only when a BACKTEST_PASS+ engine says SELL, never gates. Both behaviours are tested side by side in `tests/test_advisor_client.py`. |
| `[KEEP] eqr/strategy/rank.py`, `sleeves.py` | **Untouched.** Sumaer's brief names `rank.py` for the decision engine; the codebase's layering rule (strategy never imports rating) and the L-v1 prospective freeze put the engine one layer up in `eqr/rating/`. The only future hook is "Sleeve F" (a sleeve that trades the rating) after r2 reaches BACKTEST_PASS, through the existing walk-forward, as ×10 §8 already recommends. |
| `[KEEP] eqr/features/fundamental.py`, `xsection.py` | **Untouched** (Sleeve L-v1 inputs are frozen). `winsorise` and the grouping rule are imported, not copied. `_altman` and `_piotroski` logic is ported into `fundamentals/` with tests, the originals stay. |
| `[MODIFY] eqr/config.py`, `.env.example` | `EQR_ERP_PCT` (default 5.5), `EQR_TAX_RATE_PCT` (25), `EQR_TERMINAL_GROWTH_PCT` (5), `EQR_RATING_VARIANT` (base). Names only in docs; values never. |
| `[MODIFY] eqr/cli.py` | `metrics`, `rate --universe|--symbol [--as-of] [--variant] [--publish] [--calibrate --engine r1 --start --holdout-start]`, `decision SYMBOL [--md|--html|--telegram]`. |
| `[MODIFY] deploy/mac/jobs.py`, launchd plists, `deploy/systemd/*` | nightly chain += `["rate", "--universe", "--publish"]`; weekly += `["metrics"]` before `rate`. Installed by production-engineer. |
| `[MODIFY] eqr/spine/xbrl.py` (small) | The canonical map already carries `cost_of_materials`, `purchases`, `inventory_change`, `employee_cost`, `other_expenses`, `borrowings_current` (so gross margin is computable from XBRL as-is). Add only: `PurchaseOfPropertyPlantAndEquipment` → `capex`, `CurrentLiabilities`/`TotalCurrentLiabilities` → `current_liabilities`, `TradePayables`/`TradePayablesCurrent` → `trade_payables`, `DividendsPaid` → `dividends_paid`, `RepaymentOfBorrowings` → `debt_repaid`. Raw tags are already stored, so the backfill need not be redone: `canonical_wide` re-reads. |

### 5.2 Tasks (TDD, one fresh subagent per task, tests per task, one commit per task; pushes via production-engineer, docs via documentation-engineer)

| # | Task | Tests (must pass) | Days |
|---|---|---|---|
| R0.1 | Schema migration (`ratings`/`rating_ledger` new columns), `eqr/rating/model.py`, `sector.py` | `test_schema_v3_columns_idempotent`; `test_profile_for_bank_it_pharma_cyclical_general_default` | 0.5 |
| R0.2 | `fundamentals/base.py` (+ `mcap_series`, `borrowing` coalesce, extra screener items) | UNKNOWN has no value; grouped percentile fallback; inputs respect `visible_from`; `mcap_series` is invariant across a 1:5 split fixture (adj_close × equity_capital/face_value_current); `borrowing`/`borrowings` coalesced and flagged when both present and different | 0.5 |
| R1.1 | `moat.py` | ROIC/WACC hand example to 1e-6; spread map monotone; persistence on a 10-year fixture; bank block NA for non-banks and vice versa | 1 |
| R1.2 | `solvency.py` | net debt falls back to gross with note when cash UNKNOWN; Altman equals the existing `_altman` on the same inputs; CET1 map | 0.5 |
| R1.3 | `forensic.py` | Beneish equals the hand-computed paper example; abstains < 6 components; Sloan equals `features.accruals`; reserves leakage 0 when reserves track retained PAT; NA for BANK / NBFC_FIN | 1 |
| R1.4 | `valuation.py` | `implied_growth` recovers a planted g; DCF of a zero-growth perpetuity equals EPV; band median = 0.5; justified P/B at ROE = CoE equals 1; triangulation dispersion; MoS sign | 1 |
| R1.5 | `growth.py`, `management.py` | fundamental growth = reinvestment × ROIIC; growth gap uses the valuation's implied g; dilution from face-value history; adverse keyword fixtures; insider net-buy from `insider_trades` fixture | 1 |
| R1.6 | `build.py` + CLI `metrics` | end-to-end on `make_synthetic_market` (extended with a `planted_quality` name and a `planted_fraud` name); PIT: a metric never uses a statement with `visible_from > as_of`; slice replace is idempotent | 0.5 |
| R2.1 | `pillars.py` + `flags.py` + `confidence.py` | shrink-to-prior arithmetic with the (as_of, profile) prior; pillar UNKNOWN < 50% weight; every HARD/SOFT/WATCH flag fires on its fixture and only there; forward-only flags return UNKNOWN (not "clean") when their table is empty; DCI bands and the 0.90 screener ceiling; NO_RATING causes named | 1 |
| R2.2 | `decision.py` + `engine.py` (pure) + manifest + `tests/test_layering.py` | 30+ table-driven cases: best-in-class → CONVICTION_BUY; S 85 + MoS −30% → TRIM; hard flag + S 90 → SELL; S 82 + MoS 25% + MED DCI → SPECULATIVE_BUY (R5b); one WATCH flag blocks R5; any SOFT flag caps a BUY; LOW DCI demotes; every rule R1–R9 reachable by exactly one fixture; hysteresis up-margin; identical inputs → identical sha; no upward imports | 1 |
| R2.3 | `ledger.py` + CLI `rate` | publish idempotent; maturity uses adjusted closes + delisting haircut; ledger rows never rewritten; `rate --universe` on the synthetic market writes `ratings` rows with verdicts | 0.5 |
| R3.1 | `calibrate.py`, `acceptance.py`, `report.py` | planted signal → monotone tiers + IC; random market fails the bar; Newey–West hand value; isotonic Brier beats climatology; flag precision on the planted fraud name; coverage-neutrality anchor | 1.5 |
| R3.2 | Real r1 calibration run (2017-06-30 → holdout 2024-09 → 2025-08) | report stored in `rating_calibrations`; verdict travels with every rating; trial ledger entry | 0.5 (machine ≈ 1 h) |
| R4.1 | `surfaces/report.py` + `decision.html` + routes + digest + advisor block | every block renders from fixture data; light theme; `/decision/RELIANCE` 200; advisor `decision` present and fail-soft; `evidence_line` zeroes only on BACKTEST_PASS+ SELL | 1.5 |
| R4.2 | Dossier schema v2 + pack v2 + `render_markdown` v2 | v1 dossier still valid; `engine_decision` must equal the pack's (mismatch → REJECTED); grades need citations; engine card printed first | 1 |
| R5.1 | XBRL canonical additions (5 tags) + `moat.py`/`forensic.py`/`solvency.py` r2 components + `ENGINE_VERSION = "r2"` | new tags parse from the 2024/2026 fixtures; gross margin from the existing `cost_of_materials`/`purchases`/`inventory_change` items; Beneish 7 real components (SGAI still UNKNOWN); real cash → net debt without the investments proxy; current ratio and Altman WC from XBRL; r2 calibration from 2019-06-30 | 1 (after the backfill) |
| R6 | Jobs, version bump 0.3.0, handoff | `tests/test_launchd.py` chains; documentation-engineer updates `VALIDATION.md` (rating section), `OPERATIONS.md`, `REBUILD_SPEC.md`, `DOCS_INDEX.md`; production-engineer pushes and re-installs agents | 0.5 |

Total ≈ 14 agent-days; r1 is calibratable in week two without waiting for the XBRL backfill (which runs in the background per ×10 T1.4).

### 5.3 Pseudo-code of the engine core

```python
# eqr/rating/engine.py (pure; the only I/O is in rate_universe)
def rate_symbol(symbol, as_of, metrics: MetricSet, feat: dict, ctx: Context, variant="base") -> RatingResult:
    profile = profile_for(feat["industry"], ctx.is_bank, metrics)
    errors  = data_errors(metrics, feat, ctx)                      # §3.4 named causes
    pillars = {p: pillar_score(p, metrics, profile, variant, ENGINE_VERSION) for p in PILLARS}
    S       = composite(pillars, PROFILE_WEIGHTS[profile][variant])  # shrink-to-prior, no renormalisation
    val     = valuation_block(metrics, feat, profile)               # fv_base/bull/bear, mos, implied g, dispersion
    flags   = evaluate_flags(metrics, feat, ctx.surveillance, ctx.announcements, profile)
    conf    = data_confidence(pillars, metrics, ctx.staleness_days, ctx.source, val.dispersion, ctx.integrity)
    if errors or conf.dci < 0.35:
        return RatingResult(status="NO_RATING", data_errors=errors + conf.flags, ...)
    dec     = decide(S, val.mos_base, conf.band, flags, growth_catalyst(metrics, pillars["P4"].score), pillars["P2"].score)   # deterministic only
    dec     = apply_caps(dec, flags); dec = apply_confidence(dec, conf.band)
    dec     = hysteresis(ctx.prev_verdict, dec, S, val.mos_base)
    man     = manifest(symbol, as_of, ENGINE_VERSION, variant, profile, metrics, PROFILE_WEIGHTS, MAPS, THRESHOLDS, flags, val)
    return RatingResult(symbol, as_of, ENGINE_VERSION, variant, profile, S, pillars, flags, val, conf, dec, "RATED", [], man, sha256(man))
```

---

## 6. Verification & Backtesting Roadmap

Everything below reuses `eqr/validate/` conventions: PIT month-end signal dates, embargoed expanding folds, one-shot holdout, deflated Sharpe with the trial ledger count, quality gate on the input slice, claim ladder on the output.

### 6.1 Calibration protocol (pre-registered in `rating/acceptance.py` before the first run)

- Signal dates: month-ends from 2017-06-30 (r1) / 2019-06-30 (r2) to end − 12 months; names = PIT liquidity universe (`universe_monthly`); forward 12-month adjusted total return; delisted exit at last close × 0.99; benchmark NIFTY 500 TR proxy (+1.3%/yr) until the Wave 2 TRI ingest, labelled as such.
- Folds: expanding yearly 2019–2024 with a 12-month embargo; variant (`base`/`quality_tilt`/`value_tilt`) chosen per fold on train IC; holdout 2024-09 → 2025-08 evaluated once; DSR with 3 + prior trials.

### 6.2 Acceptance bar (all must hold for `VALIDATED`; else `NOT VALIDATED`, and the verdict travels with every rating, page pill, advisor flag, digest label)

| Check | Threshold |
|---|---|
| Score-decile forward excess return strictly monotonic overall and in ≥ 70% of test years | — |
| Verdict tiers ordered: CONVICTION_BUY > SPECULATIVE_BUY > HOLD > TRIM > SELL on mean 12m excess, each adjacent gap ≥ 0 | — |
| Long-short (BUY tiers − SELL/TRIM tiers) | ≥ 6 pp/yr, Newey–West t ≥ 2 (lag 11) |
| Mean rank IC (score vs 12m excess) | ≥ 0.05, t ≥ 2 |
| MoS IC (mos_base vs 36m excess) | ≥ 0.03 with t ≥ 1.5 (valuation is slow) |
| Hit rate (excess > 0) | CONVICTION_BUY ≥ 60%, all BUY ≥ 55%, SELL tier "hit" (excess < 0) ≥ 55% |
| HARD-flag precision (historically computable flags only: `FORENSIC_BENEISH_2Y`, `FORENSIC_CASH_DIVERGENCE`, `SOLVENCY_BREACH`, `CAPITAL_BREACH_BANK` via GNPA) | ≥ 65% of hard-flagged names have 12m excess < 0 or delist; SOFT-flag names (hist subset) underperform no-flag names of the same score decile. Forward-only flags are excluded from the bar and reported prospectively only (`CONTROLS_NO_HISTORY`) |
| Probability calibration | OOS Brier ≤ 0.24 and ≥ 0.01 better than climatology (isotonic map fitted on train folds only) |
| Coverage-neutrality anchor | IC in the HIGH-DCI cohort ≥ IC in the LOW-DCI cohort (DCI is informative), and score is not correlated with coverage (|ρ| < 0.10) |
| Sector neutrality | no profile holds > 40% of CONVICTION_BUY names on average; long-short positive within ≥ 3 of 5 profiles |
| Double-count check | `no_valuation_pillar` variant IC reported next to `base`; adopt the simpler variant if the IC difference is within one standard error |
| Stability | monthly verdict transition ≤ 25%; no verdict below 5% of the universe on average; DSR p < 0.05; holdout long-short positive |

### 6.3 Prospective validation (the final arbiter)

- Every nightly `rate --universe --publish` appends to `rating_ledger` (append-only; matured at 12 months by `mature()`); quoted only with ≥ 100 matured rows and ≥ 20 per tier; tier hit rates and excess returns on `/ratings`.
- Claim ladder per engine version: DIAGNOSTIC (no calibration) → PROVISIONAL (bar passed, integrity items open: AS_RESTATED_FUNDAMENTALS, BENCH_PROXY, CONTROLS_NO_HISTORY for the forward-only flags; MCAP_NOT_SPLIT_INVARIANT applies to the sleeves, not to Pillar 6 once `mcap_series` lands) → BACKTEST_PASS → PROSPECTIVE_VALIDATED (≥ 12 sealed months).
- Money-weighted returns of any rating-based paper portfolio are computed only by the XIRR engine (`xirr` agent) before they appear in a report; CAGR is labelled time-weighted.

### 6.4 Adversarial and invariance tests (in `tests/`, run in CI)

- Planted-signal market: a `planted_quality` name must land CONVICTION_BUY with HIGH DCI; a `planted_fraud` name (Beneish > −1.78 two years under the 5-real + 2-proxy r1 rule, Sloan accruals 12%) must be SELL with `FORENSIC_BENEISH_2Y` regardless of its (high) score; a second `planted_cash_divergence` name (accruals 16% two years, CFO/PAT 0.3) must trip `FORENSIC_CASH_DIVERGENCE`.
- No-look-ahead: shifting a statement's `visible_from` one day after `as_of` changes the manifest and the affected metrics become UNKNOWN.
- Determinism: same inputs → same `manifest_sha` across two processes.
- Coverage invariance: deleting a non-critical component moves the score toward the prior by exactly `w_i·(c_i − prior)/Σw`, and lowers DCI.
- Split invariance: a 1:5 split fixture leaves ROIC, MoS and dilution unchanged.
- Sector profile: a bank or NBFC never receives Beneish/Altman/FCF/net-debt components; a non-financial never receives CET1/GNPA/leverage-map components; every one of the 73 live industry strings is explicitly mapped (test reads the list from a fixture snapshot of `instruments.industry`).
- Forward-only flags: with `pledges`, `credit_ratings`, `insider_trades`, `announcements` empty for a symbol, the corresponding flags are UNKNOWN (not fired, not "clean") and the affected components shrink to the prior.
- Layering: `strategy` and `features` import nothing from `rating`/`fundamentals`/`research`.

### 6.5 Definition of done for Wave 3 / Layer 1

`pytest -q` green with the new suites; `eqr metrics --monthly-from 2017-06-30` complete; `eqr rate --calibrate --engine r1` report stored with the acceptance table; `eqr rate --universe --publish` nightly on the Mac; `/decision/RELIANCE`, `/ratings` render; advisor `decision` block live; documentation-engineer's `VALIDATION.md` rating section committed; production-engineer's deploy ledger entry.

---

## Appendix A — Design reasoning trail (the step-by-step thinking behind the choices)

1. **Read the code first.** `rank.py`/`sleeves.py` are a portfolio constructor; `dossier.py` lets the LLM write the rating; `fundamental.py` is a 30-metric screener battery; ×10 tables and the XBRL parser already exist, empty. The decision engine therefore belongs in a new `eqr/rating/` layer, not in `rank.py`, and must not disturb the frozen L-v1 numbers.
2. **Map ×10's eight pillars onto Sumaer's six.** Quality → P1 (with ROIC−WACC added as the anchor); Forensic → P3; Growth → P4 (with reinvestment × ROIIC); Valuation → P6 (with six FV models and MoS); Governance → P5; Momentum → out of the fundamental score (timing tag); Graph-risk → P5/P2 components in r3; Qualitative → capped LLM grades inside P1/P4/P5 in r3.
3. **Absolute anchors where relative scoring lies.** Spread, leverage, coverage, accruals, Beneish, pledge, CET1 and GNPA use fixed maps; only peer-relative items (margins, growth, yields) use percentiles. A sector that destroys value cannot score well by being "relatively" fine.
4. **Score ≠ confidence ≠ verdict.** Three separate objects; the decision matrix consumes all three plus MoS and flags in a fixed rule order, with price beating quality when overvaluation exceeds 25%.
5. **Sequencing by data availability.** r1 on screener today (calibratable over 2017→), r2 when XBRL lands (gross margin, cash, receivables, full Beneish), r3 when documents/graph/verified dossiers exist.
6. **Output shaped for a decision, not a dashboard.** One verdict callout, one MoS, one confidence, six bars, three risks, what would change it, and the provenance line, all on one page.

## Appendix B — Divergences from the Fundamentals ×10 plan (§3.5) that this plan asks Sumaer to approve

| ×10 §3.5 | This plan | Why |
|---|---|---|
| 8 pillars incl. Momentum 0.10 | 6 pillars; momentum is a timing tag | A fundamental score should not move with price; momentum stays in the sleeves |
| Absent pillars renormalised away | Shrink to the prior; DCI records the gap | Final Plan doctrine (later, reference tier) |
| Notch map STRONG_BUY ≥ 80 / BUY ≥ 65 / HOLD ≥ 40 / REDUCE ≥ 25 | Decision matrix with MoS, catalyst, risk and DCI conditions (§4.1) | Sumaer's brief; a score alone cannot say "good company, wrong price" |
| Gates cap the notch | Same, split into HARD (SELL) and SOFT (HOLD/TRIM) tiers with evidence | Explicit override engine |
| Single weight set + financial variant | Six sector profiles (GENERAL, BANK, NBFC_FIN, IT_SERVICES, PHARMA, CYCLICAL) mapped over the 73 live NSE industry strings × 3 variants (+ `with_qual` r3, never default) | Sumaer's brief; banks need NIM/NPA/CET1, NBFCs need leverage and funding cost, cyclicals need mid-cycle multiples |
| Qualitative pillar 0.05 in the default engine | LLM grades only inside the separately calibrated `with_qual` variant; deterministic growth catalyst | Final Plan doctrine "LLM output never moves a deterministic rating" |
| Valuation = yields + bands + growth gap | Adds six-model FV triangulation and MoS | Margin of safety is the decision axis |
| Confidence formula | Data Confidence Index with source, dispersion and coverage factors; demotes conviction | Score/confidence separation made operational |
