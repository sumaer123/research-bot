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

## Running on the Mac (launchd)

Four user agents (web dashboard, refresh, fundamentals, digest) run unattended via launchd in
`gui/$(id -u)`. Install or reinstall after pulling new code:

```
bash deploy/mac/install-mac.sh
```

The script is idempotent: it renders the four plist files (with `__ROOT__` and `__LOGS__` placeholders),
validates them (`plutil -lint`), and loads them into launchd. Logs go to `~/Library/Logs/eqr/` as plain-text
files: `<agent>.log` (stdout) and `<agent>.err` (stderr/tracebacks).

### Schedules (IST)

| Agent | Trigger | What |
|---|---|---|
| `com.eqr.web` | always, KeepAlive | Dashboard + advisor API on 127.0.0.1:8801; check health: `curl http://127.0.0.1:8801/health` (200 = running) |
| `com.eqr.refresh` | daily 19:45 | `eqr refresh`, then `eqr reference --from <today-45d>` |
| `com.eqr.fundamentals` | Saturday 02:00 | `eqr fundamentals --rate 1.5`, then `eqr features`, then `eqr rank --sleeve L` and `--sleeve S` |
| `com.eqr.digest` | daily 07:30 | `eqr digest --send` (prints to log: `{"sent": false}` if `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` unset, as expected) |

### TCC (Transparency, Consent & Control) gotcha

The `.venv/bin/python` interpreter holds the "Downloads folder" grant (from where the project lives).
The console script `eqr` (which wraps `python -m eqr.cli:app`) runs `/bin/sh`, which does not have that
grant. A plist that execs the `eqr` script will exit 126 on the Mac. **Always exec `.venv/bin/python` directly in plists**, as the installer does — the working directory is set correctly.

### Logs

```
# Tail all eqr agents in real-time:
tail -f ~/Library/Logs/eqr/*.log

# Last run of digest (stdout + stderr):
tail -30 ~/Library/Logs/eqr/digest.log
tail -30 ~/Library/Logs/eqr/digest.err
```

For agent state (running, last-exit time):

```
launchctl print gui/$(id -u)/com.eqr.web | grep -E 'state|last exit'
```

### Remove

To unload all agents:

```
bash deploy/mac/install-mac.sh --remove
```

### Relation to the VM

Everything here runs on the Mac today. The planned future is a Hetzner or GCP VM running Ubuntu 24.04
with the same `eqr` code, but using `deploy/install.sh` (not the Mac installer) and systemd timers
(not launchd). The command/schedule logic is shared: `deploy/mac/jobs.py` and `deploy/systemd/*.timer`
both invoke the same CLI commands. Switching to the VM is a one-time handoff — once the VM is live,
the Mac agents can be unloaded.

## Known open items

- **Survivorship gap for delisted names (Sleeve L only).** Delisted names keep their price
  history (the bhavcopy archive is the source of record) but never had a screener.in page, so
  Sleeve L's fundamentals — and therefore its backtest — only ever see survivors: 823 of the
  1,225 names in the 2017-21 universe. Sleeve S is price-only and free of this bias. Closing the
  gap means fetching statements for the ~450 delisted names by their BSE code — not started.
- **Sleeve S redesign hypothesis.** Sleeve S failed validation (NOT VALIDATED, see
  `docs/VALIDATION.md`) because its weekly design churns the entire book every week (turnover
  ~2,000%/yr, costs ~1,180 bps/yr). An exploratory, post-hoc (not pre-registered, not validated)
  run of a minimum-hold rule — 20 sessions minimum, hold while inside 3N, no trims, full period
  2019-2026 — moved the N=20 flow-tilt variant from Sharpe 0.01 to 0.61 and turnover from 2,071%
  to 926%, but it still only matched the index (CAGR 15.3% vs 14.0%, IR 0.06) after ~469 bps/yr
  of costs — promising on turnover, not yet an edge. The next pre-registered experiment is 8-12
  week holds with a signal that actually clears the cost line, not just a longer hold on the
  same signal. Sleeve S stays a diagnostic line only until a fresh, pre-registered run passes
  the acceptance bar in `docs/VALIDATION.md`.
- **VM not yet provisioned.** The Mac (launchd) is production for now. No Hetzner/GCP account has
  been created for this project; `deploy/install.sh` is untested against a real box. The future
  non-OCI VM will run the same code via systemd instead of launchd.
- **Telegram token not set.** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are blank in `.env`
  (see `.env.example`) — `eqr digest` prints fine, but `--send` will fail until both are set.
