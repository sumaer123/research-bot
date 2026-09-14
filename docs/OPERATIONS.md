# Operations — Sumaer Research Bot (`eqr`)

Runbook for day-to-day use on the Mac today; the same commands apply once the VM exists
(`docs/REBUILD_SPEC.md` §9 automates the schedule below via systemd).

## Daily

1. `eqr refresh` — loads today's EOD prices/index closes/snapshots (or `--date YYYY-MM-DD` for a
   specific session; `--backfill-from`/`--backfill-to` for a range). Prints a JSON summary —
   check it for any source that came back `missing`/`blocked`/`error` rather than `ok`.
2. `eqr reference --from <45 days ago>` — rolling refresh of corporate actions, filing dates and
   surveillance lists (this is what the VM's `eqr-refresh.service` chains automatically after
   `refresh`; run it by hand on the Mac).
3. `eqr digest` — prints the Telegram digest (regime, entries/exits since yesterday per sleeve,
   results due today, data-quality failures) without sending. Add `--send` only once
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set — see "Known open items" below.

## Weekly

1. `eqr fundamentals --fetch-only` then `eqr fundamentals --load-raw` — screener.in sweep
   (~2,000 symbols at <=1 req/s takes hours; `--fetch-only` is DB-free and safe to run in the
   background while something else holds the DuckDB file, `--load-raw` parses what was
   archived). Watch the printed `ok`/`missing`/`blocked` counts; 5 blocks in a row stops the
   sweep early rather than hammering a rate limit or a changed page.
2. `eqr factors` — re-detect split/bonus adjustment factors from any new `PREV_CLOSE`
   restatements.
3. `eqr features --monthly-from <last run date>` — extend the feature table to the newest
   month-end (or `--as-of` for a single date).
4. `eqr rank --sleeve L` and `eqr rank --sleeve S` — refresh both sleeves' target weights using
   whichever configuration the latest `eqr validate` run selected (`validated_config`); pass
   `--top`/`--variant` only to deliberately override that choice.

## Quality checks — what a FAIL means

`eqr refresh` runs the quality harness after every load (spec §4.4); failures land in the
`quality_checks` table and the Telegram digest, never silently:

| Check | FAIL means |
|---|---|
| Bhavcopy row count outside [1,500, 3,000] EQ rows | the day's file is truncated, duplicated, or NSE changed the series mix — do not trust that day's ranks until checked |
| Duplicate keys | the same (symbol, trade_date) loaded twice — a re-run or a parser regression |
| NIFTY 50 / NIFTY 500 / India VIX missing | the index-close file didn't load — regime detection will be wrong for that date |
| Price jump > 50% with no adjustment factor | either a real corporate action `adjust.py` hasn't confirmed yet (check `factor_anomalies`), or a bad print — do not size into the name until resolved |
| Delivery coverage < 90% of EQ rows | the MTO/delivery column didn't load for enough names — Sleeve S's delivery-surge signal degrades silently below this |
| Statements freshness low | the share of the universe with a statement visible in the last 120 days has dropped — usually means the weekly `fundamentals` sweep is falling behind (check for repeated `blocked` runs) |

`eqr doctor` is the fast path to isolate WHERE a problem is: one live fetch per source (NSE
archives, NSE API) plus row counts for the core tables, printed one line each. Run it first
whenever a refresh looks wrong.

`eqr validate`/`eqr backtest` are meant to refuse a date range carrying open quality failures
unless forced (spec §10) — deliberately, so a bad data day cannot silently produce a wrong
verdict.

## Running a dossier on the Mac

```
.venv/bin/eqr pack RELIANCE                       # build the JSON evidence pack only, no LLM call
.venv/bin/eqr dossier RELIANCE --dry-run           # build the pack + prompt, print it, no LLM call
.venv/bin/eqr dossier RELIANCE                     # full run: builds the pack, calls Claude, validates, stores
```

Claude runs via the `claude` CLI session on the Mac by default, or the Anthropic API if
`ANTHROPIC_API_KEY` is set (`EQR_CLAUDE_MODEL` picks the model either way). Every claim in the
returned dossier must cite a `[doc_id]` or a named table; the JSON block is validated against
`eqr/research/schema.json`, and a dossier with an unsupported claim is **rejected outright, not
partially stored** — re-run `--dry-run` first if a dossier keeps failing, to see the exact prompt
and pack Claude is working from. Dossiers never change a rank; they are informational only.
Claude never runs unattended on a VM — this command is always run from the Mac, by hand, on
request.

## How the Upstox integration is meant to work later (R6)

Nothing is wired up yet — this is the plan, not the current state. Once a sleeve is VALIDATED in
a production run (Sleeve L qualifies today; see `docs/VALIDATION.md`) and the advisor API is
reachable from wherever Upstox runs, Upstox's own R6 phase copies
`eqr/surfaces/advisor_client.py` into its codebase and calls `GET
/advisor/v1/evidence/{symbol}` with the `EQR_ADVISOR_TOKEN` bearer. The contract is fail-soft by
construction on both ends: any transport error, non-200, `STALE` or `UNKNOWN` response is treated
as an UNKNOWN check by the caller — it can add at most one check's worth of points to whatever
Upstox already scores, and it can never remove or weaken a gate Upstox already has. This project
never calls into Upstox, never reads its data, and is never deployed to the OCI box (Upstox-only,
per standing project doctrine). Building R6 itself is Upstox's work, tracked in that project's
own docs, not here.

## Known open items

- **Survivorship gap for delisted names (Sleeve L only).** Delisted names keep their price
  history (the bhavcopy archive is the source of record) but never had a screener.in page, so
  Sleeve L's fundamentals — and therefore its backtest — only ever see survivors: 823 of the
  1,225 names in the 2017-21 universe. Sleeve S is price-only and free of this bias. Closing the
  gap means fetching statements for the ~450 delisted names by their BSE code — not started.
- **Sleeve S redesign hypothesis.** Sleeve S failed validation (NOT VALIDATED, see
  `docs/VALIDATION.md`) because its weekly design churns the entire book every week (turnover
  ~2,000%/yr, costs 1,180-1,360 bps/yr) — the next pre-registered experiment is a hold-period
  discipline (minimum four weeks, exit only on a stop or falling past rank 3N), not a new signal.
  Not started; Sleeve S stays a diagnostic line only until it passes a fresh, pre-registered run.
- **VM not yet provisioned.** Everything above runs on the Mac only. No Hetzner/GCP account has
  been created for this project; `deploy/install.sh` is untested against a real box.
- **Telegram token not set.** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are blank in `.env`
  (see `.env.example`) — `eqr digest` prints fine, but `--send` will fail until both are set.
