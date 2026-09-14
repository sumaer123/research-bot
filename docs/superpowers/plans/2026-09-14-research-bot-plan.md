# Sumaer Research Bot — Implementation Plan (2026-09-14)

Spec: `docs/superpowers/specs/2026-09-14-research-bot-design.md`. Each task ends with a
test that ran or a real command whose output is recorded in the PR description.

| # | Task | Done when |
|---|---|---|
| 1 | Package skeleton: pyproject, config, `.env.example`, `.gitignore`, CLI stub | `eqr --help` works from the venv |
| 2 | Store: schema.sql, connect/init, upsert, `as_of_view` | `tests/test_store.py` passes |
| 3 | Spine/http: rate-limited session, retries, NSE cookie warm-up, proxy, raw archive | `tests/test_http.py` (offline) passes |
| 4 | Spine/archives: bhavcopy (3 formats), MTO, index closes, EQUITY_L, ban, deals parsers | fixture tests pass; `eqr refresh --date 2026-09-11` loads real rows |
| 5 | Spine/adjust + universe + quality harness | split fixture recovers factor 0.5; quality run prints PASS |
| 6 | Backfill 2016-01-01 → today in background | row counts per year logged |
| 7 | NSE API: corporate actions, results calendar, ASM/GSM, announcements, shareholding | live smoke for 1 symbol |
| 8 | Screener parser (full tables) + statements loader with PIT visibility | fixture test; live RELIANCE load |
| 9 | Features: price, fundamental, valuation, cross-section | `eqr features --as-of` on real data |
| 10 | Strategy: regime, sleeves, sizing, rank | `eqr rank --sleeve L` writes ranks |
| 11 | Validate: costs, backtest, walk-forward, metrics, acceptance, report | planted-signal test; real backtest report |
| 12 | Research: docstore, pack, schema, dossier runner | pack builds for RELIANCE; schema tests |
| 13 | Surfaces: web, advisor API, digest/Telegram | TestClient tests; screenshot of dashboard |
| 14 | Deploy artefacts: install.sh, systemd, Caddyfile, backup | shellcheck-clean |
| 15 | Docs (documentation-engineer), registry + push (production-engineer) | PR open |
