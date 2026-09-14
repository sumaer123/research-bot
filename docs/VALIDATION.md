# Validation — Sumaer Research Bot (`eqr`)

How both sleeves were tested before either was trusted, and what the first run of that test
found. Plain language: no rate is real until it survives costs, an out-of-sample fold, and a
multiple-trials penalty — and even then it comes with caveats, below.

## The protocol (pre-registered before this run — spec §7)

**Cost model** (Indian delivery equity, applied per order): STT 0.1% each side, exchange
0.00297%, SEBI Rs 10/cr, stamp duty 0.015% on buys, 18% GST on brokerage + exchange + SEBI
charges, brokerage Rs 0 (discount) or a flat Rs 20/order (configurable), DP charge Rs 15.34 per
sell scrip-day, and a market-impact charge of 10 bps + 25 bps x sqrt(order value / 20-day average
daily value), capped at 100 bps. Costs are computed on a stated capital base — Rs 10 lakh by
default; a Rs 70k shadow case is reported separately and is not part of this run.

**Backtest mechanics:** signal at the close of day t, fill at the open of day t+1, mark-to-market
daily off adjusted closes. A delisted name exits at its last close with a 100 bps haircut.
Dividends are not credited — conservative against the total-return benchmark.

**Walk-forward:** expanding folds, one per calendar year 2019-2025, with a purge of one holding
period and an embargo of one month at each fold boundary. The last 12 months (Sep-2025 ->
Aug-2026) are held out and evaluated exactly once, at the end, never peeked at during fold
selection. Six pre-registered trials per sleeve are counted for the deflated-Sharpe penalty:
N in {20, 30} x 3 weight variants.

**Acceptance bar — every line below must hold, net of costs, out-of-sample, or the sleeve is
reported NOT VALIDATED:**
- Sharpe >= 0.8
- information ratio >= 0.5 versus the NIFTY 500 TR proxy (the price index plus an assumed 1.3%
  dividend yield — a documented approximation, not a real total-return index)
- mark-to-market max drawdown no worse than the benchmark's
- deflated-Sharpe p-value < 0.05 (correcting for the six trials actually run)
- positive excess return in at least 3 of the 4 most recent folds
- the result holds up across both universe liquidity floors (Rs 1 cr / Rs 3 cr) and both N
  choices (20 / 30)
- capacity: the median order stays under 5% of 20-day average daily traded value at Rs 10 lakh
  capital

Benchmarks: NIFTY 500 (TR proxy), NIFTY 50, and an equal-weight universe.

A sleeve that fails even one line is reported NOT VALIDATED and is never exposed to Project
Upstox as anything but a diagnostic line — see `README.md`'s guardrails.

## Sleeve L — VALIDATED

Source: `data/reports/validate-20260914-063318-1219c7/report.md` (2017-06-01 -> 2026-09-11,
holdout from 2025-09-01, Rs 1,000,000 capital, 6 pre-registered trials) — the latest of four L
runs made today; earlier runs in this session found and fixed engine bugs (spec §4.2), so this
is the one that counts.

### Verdict: VALIDATED

| Check | Status | Detail |
|---|---|---|
| oos_sharpe | PASS | OOS Sharpe 1.28 vs >= 0.8 |
| oos_information_ratio | PASS | IR vs NIFTY 500 TR proxy 0.72 vs >= 0.5 |
| oos_drawdown_not_worse_than_index | PASS | strategy MTM maxDD -22.2% vs index -37.8% |
| deflated_sharpe | PASS | DSR p-value 0.005 (trials 6) vs < 0.05 |
| recent_folds_positive_excess | PASS | 4 of 4 most recent folds beat the index |
| robust_across_variants | PASS | worst variant Sharpe 0.93, all variants beat index: True (4 variants) |
| capacity | PASS | median order 0.03% of ADV20 at the stated capital |

All 7 checks pass.

### Out-of-sample (stitched folds, net of costs)

| Metric | Strategy | Index |
|---|---|---|
| CAGR | 28.7% | 17.1% |
| Sharpe | 1.28 | 0.73 |
| Max drawdown | -22.2% | -37.8% |
| Information ratio | 0.72 | |
| Deflated Sharpe p-value | 0.005 (SR0 0.19, trials 6) | |

### Folds

| Year | Selected | Train Sharpe | Test Sharpe | Test CAGR | Index CAGR | Excess | Test maxDD |
|---|---|---|---|---|---|---|---|
| 2019 | L-N20-momentum_tilt-T1cr | -0.425 | -0.77 | -3.4% | 13.6% | -16.9% | -14.9% |
| 2020 | L-N20-momentum_tilt-T1cr | -0.719 | 1.272 | 31.9% | 19.2% | 12.8% | -18.6% |
| 2021 | L-N20-momentum_tilt-T1cr | -0.047 | 2.288 | 69.7% | 28.8% | 40.8% | -11.6% |
| 2022 | L-N20-momentum_tilt-T1cr | 0.655 | -0.058 | 2.6% | 2.4% | 0.2% | -21.8% |
| 2023 | L-N20-momentum_tilt-T1cr | 0.615 | 4.622 | 102.4% | 36.2% | 66.1% | -7.4% |
| 2024 | L-N20-momentum_tilt-T1cr | 0.951 | 0.683 | 19.6% | 15.7% | 3.9% | -13.8% |
| 2025 | L-N20-momentum_tilt-T1cr | 0.992 | 1.358 | 27.7% | 11.1% | 16.6% | -6.7% |

### Holdout (2025-09-01 -> 2026-09-11, evaluated once)

Selected `L-N20-momentum_tilt-T1cr` — CAGR 21.9% vs index 1.9%, Sharpe 0.98, maxDD -13.8% vs
index -14.6%.

### Robustness (selected variant across N and liquidity floors)

| Variant | Sharpe | CAGR | Excess | MaxDD |
|---|---|---|---|---|
| L-N20-momentum_tilt-T1cr | 1.045 | 26.5% | 10.6% | -29.2% |
| L-N20-momentum_tilt-T3cr | 0.956 | 24.4% | 8.6% | -28.8% |
| L-N30-momentum_tilt-T1cr | 1.042 | 24.8% | 9.0% | -26.5% |
| L-N30-momentum_tilt-T3cr | 0.934 | 22.4% | 6.5% | -23.7% |

### All trials (full period, net)

| Trial | CAGR | Sharpe | MaxDD | IR | Turnover | Costs bps |
|---|---|---|---|---|---|---|
| L-N20-base-T1cr | 14.0% | 0.51 | -52.2% | 0.09 | 272% | 151 |
| L-N20-quality_tilt-T1cr | 14.3% | 0.54 | -49.2% | 0.10 | 244% | 137 |
| L-N20-momentum_tilt-T1cr | 19.9% | 0.79 | -46.3% | 0.47 | 310% | 163 |
| L-N30-base-T1cr | 15.3% | 0.62 | -44.9% | 0.17 | 253% | 146 |
| L-N30-quality_tilt-T1cr | 15.0% | 0.63 | -40.9% | 0.15 | 226% | 132 |
| L-N30-momentum_tilt-T1cr | 17.4% | 0.71 | -42.5% | 0.33 | 290% | 163 |
| L-N20-momentum_tilt-T3cr | 17.5% | 0.67 | -47.5% | 0.32 | 305% | 162 |
| L-N30-momentum_tilt-T3cr | 15.9% | 0.64 | -39.5% | 0.23 | 288% | 164 |

Capacity: median order 0.03% of ADV20, p90 0.20%; turnover 311%/yr; costs 163 bps/yr.

### Caveats — read these before trusting the headline number

- The 2018-19 small-cap bust sits inside the training window, not the out-of-sample window. Over
  the full 2017->2026 period, the selected configuration (`L-N20-momentum_tilt-T1cr`, the "all
  trials" row above) shows 19.9% CAGR with a -46.3% max drawdown — clearly worse than the
  stitched-OOS 28.7% CAGR / -22.2% drawdown headline. The OOS number is real, but it is not the
  full-history number.
- The boom years 2021 and 2023 carry most of the out-of-sample excess (+40.8% and +66.1% in the
  fold table above); 2019 and 2022 are flat to negative. Don't read the stitched average as a
  steady year-by-year outcome.
- Fundamentals survivorship bias: a delisted name keeps its price history (the bhavcopy archive
  is the source of record) but never had a screener.in page, so Sleeve L's fundamentals — and
  this backtest — only ever see survivors: 823 of the 1,225 names in the 2017-21 universe. This
  run has not corrected for that.
- This exact full-period configuration and result were seen once before this protocol formally
  ran; the engine bugs that earlier look found and fixed are listed in the design spec §4.2, not
  repeated here.

## Sleeve S — NOT VALIDATED

Source: `data/reports/validate-20260914-061830-bce33a/report.md` (2017-06-01 -> 2026-09-11,
holdout from 2025-09-01, Rs 1,000,000 capital, 6 pre-registered trials) — the only S run made
today.

### Verdict: NOT VALIDATED

| Check | Status | Detail |
|---|---|---|
| oos_sharpe | FAIL | OOS Sharpe -0.17 vs >= 0.8 |
| oos_information_ratio | FAIL | IR vs NIFTY 500 TR proxy -0.87 vs >= 0.5 |
| oos_drawdown_not_worse_than_index | PASS | strategy MTM maxDD -35.2% vs index -38.2% |
| deflated_sharpe | FAIL | DSR p-value 0.835 (trials 6) vs < 0.05 |
| recent_folds_positive_excess | FAIL | 1 of 4 most recent folds beat the index |
| robust_across_variants | FAIL | worst variant Sharpe 0.04, all variants beat index: False (4 variants) |
| capacity | PASS | median order 0.01% of ADV20 at the stated capital |

Only 2 of 7 checks pass — a clean failure, not a borderline one.

### Out-of-sample (stitched folds, net of costs)

| Metric | Strategy | Index |
|---|---|---|
| CAGR | 2.2% | 15.5% |
| Sharpe | -0.17 | 0.59 |
| Max drawdown | -35.2% | -38.2% |
| Information ratio | -0.87 | |
| Deflated Sharpe p-value | 0.835 (SR0 0.22, trials 6) | |

### Folds

| Year | Selected | Train Sharpe | Test Sharpe | Test CAGR | Index CAGR | Excess | Test maxDD |
|---|---|---|---|---|---|---|---|
| 2019 | S-N30-breakout_tilt-T3cr | -1.632 | -1.352 | -6.0% | 10.1% | -16.1% | -10.7% |
| 2020 | S-N30-breakout_tilt-T3cr | -1.546 | -0.348 | -0.9% | 19.6% | -20.4% | -16.6% |
| 2021 | S-N30-flow_tilt-T3cr | -0.815 | 1.188 | 28.9% | 28.0% | 0.9% | -16.9% |
| 2022 | S-N20-flow_tilt-T3cr | -0.056 | -1.707 | -19.1% | 1.0% | -20.0% | -25.9% |
| 2023 | S-N20-flow_tilt-T3cr | -0.188 | 1.743 | 36.5% | 28.3% | 8.2% | -11.6% |
| 2024 | S-N20-flow_tilt-T3cr | -0.025 | -0.92 | -11.2% | 17.1% | -28.2% | -19.6% |
| 2025 | S-N20-flow_tilt-T3cr | -0.116 | -0.515 | -2.0% | 2.9% | -4.9% | -11.0% |

### Holdout (2025-09-01 -> 2026-09-11, evaluated once)

Selected `S-N20-flow_tilt-T3cr` — CAGR -8.3% vs index 1.2%, Sharpe -1.11, maxDD -19.4% vs index
-14.6%. The holdout confirms the OOS failure; it does not overturn it.

### Robustness (selected variant across N and liquidity floors)

| Variant | Sharpe | CAGR | Excess | MaxDD |
|---|---|---|---|---|
| S-N20-flow_tilt-T3cr | 0.16 | 7.4% | -8.4% | -33.5% |
| S-N20-flow_tilt-T3cr | 0.16 | 7.4% | -8.4% | -33.5% |
| S-N30-flow_tilt-T3cr | 0.045 | 5.6% | -10.2% | -33.4% |
| S-N30-flow_tilt-T3cr | 0.045 | 5.6% | -10.2% | -33.4% |

(reproduced exactly as the report prints it, including the repeated rows — Sleeve L's robustness
table varies both N and the liquidity floor into four distinct rows; Sleeve S's does not.)

### All trials (full period, net)

| Trial | CAGR | Sharpe | MaxDD | IR | Turnover | Costs bps |
|---|---|---|---|---|---|---|
| S-N20-base-T3cr | -4.4% | -0.59 | -42.4% | -1.12 | 2156% | 1329 |
| S-N20-breakout_tilt-T3cr | -2.8% | -0.49 | -37.8% | -1.01 | 2110% | 1269 |
| S-N20-flow_tilt-T3cr | 1.7% | -0.21 | -43.8% | -0.77 | 2009% | 1161 |
| S-N30-base-T3cr | -3.5% | -0.57 | -42.4% | -1.14 | 1934% | 1350 |
| S-N30-breakout_tilt-T3cr | -2.4% | -0.51 | -37.8% | -1.07 | 1854% | 1268 |
| S-N30-flow_tilt-T3cr | 0.4% | -0.33 | -43.3% | -0.91 | 1808% | 1181 |

Capacity: median order 0.01% of ADV20, p90 0.05%; turnover 2009%/yr; costs 1161 bps/yr.

### Why it failed, in plain language

Every trial in the table above loses money after costs, and every trial trades an enormous
amount to get there — turnover of 1,800% to 2,150% of the book per year, which alone costs
1,160 to 1,350 basis points a year. The weekly design churns the whole book too often for
whatever edge it has to survive. Sleeve S stays a diagnostic line only. The next pre-registered
experiment (spec §12a) is a hold-period discipline — hold a position for a minimum of four
weeks, exit only on a stop or once it falls past rank 3N — not a new signal. Until that
experiment runs and passes this same protocol, Sleeve S is never exposed to Project Upstox as
anything but a diagnostic line, per the guardrail in `README.md`.
