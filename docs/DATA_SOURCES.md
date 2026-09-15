# Data Sources — Sumaer Research Bot (`eqr`)

Every external source this project reads (or, for Telegram/Anthropic/B2, writes to). Live fetches
are rate-limited to <=1 request/second, and every raw fetch is cached to `data/raw/` before
anything is parsed — a parser failure never loses the bytes it failed to parse. Public reachability
does not establish permission: source terms and account authorization still govern use. URL
builders and parsers live in `eqr/spine/`.

## NSE archives (no cookies, no login) — `eqr/spine/nse_archives.py`

Base `https://nsearchives.nseindia.com`. Cadence: daily EOD unless noted; PIT rule: `as_of` =
`trade_date`, `visible_from` = same day (published after market close).

| Source | URL pattern | History depth verified | Notes |
|---|---|---|---|
| Bhavcopy — old zip format | `/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip` | 2010 -> 2024-07-31 (`OLD_END`) | discontinued by NSE mid-2024; attempted for dates on or before `OLD_END`; used for the 2016-2020 backfill window |
| Bhavcopy — UDiFF format | `/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | 2024-01-08 (`UDIFF_START`) -> present | NSE's newer bhavcopy standard; attempted first for dates on or after `UDIFF_START`, overlapping the old format for ~7 months during the 2024 cutover |
| Bhavcopy — `sec_bhavdata_full` | `/products/content/sec_bhavdata_full_{DDMMYYYY}.csv` | ~2020 -> present, verified 2026-09-11 | attempted at every date regardless of the cutover above; the only one of the three carrying OHLC + VWAP + turnover + trades + delivery in one file, so it is the field-richest, always-tried candidate (`eqr/spine/refresh.py` builds an ordered attempts list: UDiFF/old-format first when their date window applies, `sec_bhavdata_full` always) |
| MTO delivery file | `/archives/equities/mto/MTO_{DDMMYYYY}.DAT` | 2016 -> present | delivery quantity for the pre-2020 window, where `sec_bhavdata_full` doesn't carry it |
| Index closes | `/content/indices/ind_close_all_{DDMMYYYY}.csv` | 2014 -> present | NIFTY 50/500, India VIX, P/E, P/B, div yield; occasionally carries a stray row dated another day — filtered to the file's own date, not the URL date |
| Instrument master | `/content/equities/EQUITY_L.csv` (`URL_EQUITY_L`) | daily snapshot | face value, listing date, series |
| NIFTY 500 constituents | `/content/indices/ind_nifty500list.csv` (`URL_NIFTY500`) | daily snapshot | index membership is NOT used for universe eligibility (spec §4.3) — read for the index list only |
| F&O ban list | `/content/fo/fo_secban.csv` (`URL_FO_BAN`) | daily snapshot | one of the Sleeve L/S exclusion filters |
| Bulk / block deals | `/content/equities/bulk.csv`, `/content/equities/block.csv` | daily snapshot | |
| ETF list | `/content/equities/eq_etfseclist.csv` (`URL_ETF_LIST`) | daily snapshot | ETFs trade in the EQ series and are excluded via this file (spec §4.2) |

**Failure mode:** a parser that doesn't find its expected columns raises `ParseError` rather than
guessing; the refresh orchestrator logs it as an `error` `FetchResult`, never a crash. A missing
archive on a weekday after 19:00 IST is retried on the next run (spec §10).

## NSE API (cookie-gated) — `eqr/spine/nse_api.py`, `eqr/spine/http.py`

Base `https://www.nseindia.com/api/*`. Auth: a cookie warm-up (visit the home page, no login) via
`NseApi`, with one re-warm attempt on 401/403. Cadence: daily or on demand. Delivers: corporate
actions, financial-results filing dates, announcements (PDF links), ASM/GSM/ESM surveillance
lists, shareholding, annual-report links. PIT rule: `as_of` = the fact's own date (ex-date for
actions, filing date for results, quarter-end + 21d for shareholding per the SEBI deadline);
`visible_from` tracks when NSE actually published it, not when this project fetched it.

**Failure mode:** verified returning HTTP 200 from this Mac's residential IP; datacenter IPs
(i.e. most VMs) get a 403 storm, handled by falling back to the `EQR_PROXY` SOCKS5h WARP tunnel
plus a digest warning — this is the one integration point most likely to need attention the day
the VM is provisioned. `eqr doctor` checks it live (`/api/reportASM`).

## screener.in — `eqr/spine/screener.py`

Base `https://www.screener.in`. Cadence: weekly full sweep plus daily for symbols with a fresh
result. Delivers: 12 years of annual P&L/balance-sheet/cash-flow/ratios, 13 quarters,
shareholding, results-PDF links — parsed by regex over landmark page sections, not a fixed HTML
schema. Screener's official help describes premium CSV export and explicitly says it does not
provide an API; this integration must not be described as an official API or as evidence of
scraping permission. PIT rule: screener shows the latest **restated** numbers; this project stores every fetch
with `fetched_at` and keeps the FIRST-seen value per (symbol, statement, period_end, line item)
as the PIT value (table `statements`); later fetches land in `statement_revisions`. Before a
symbol's first fetch date, its history is as-restated — a known, documented bias, not a bug.
Filing dates for `visible_from` come from two NSE feeds (legacy `corporates-financial-results`
through early 2025, `integrated-filing-results` from 2025) — 84% of quarterly statements since
2016 carry a real filing date (median lag 42 days); the rest fall back to `period_end + 45d`
(Q1-Q3) or `+ 60d` (Q4/annual). Before mid-2023, screener's own trailing metrics fall back to the
last visible fiscal year (`stmt_age_days` on the row shows the staleness).

**Failure mode:** a page-structure change degrades to a quality flag, never a crash (`fetch_page`
returns a `blocked`/`missing` status rather than raising); `eqr fundamentals --fetch-only` stops
itself after 5 consecutive blocks rather than burning the rest of the run against a rate limit or
a changed page.

## Benchmark roadmap sources — not live functionality

The 2026-09-15 [fundamental-research benchmark](../INDIAN_EQUITY_FUNDAMENTAL_RESEARCH_BENCHMARKS.md)
identifies the next authoritative-data work. This is a coverage ledger for proposed work, not a
claim that these feeds or outputs are populated:

| Area | Current live state in the benchmark snapshot | Roadmap contract before use |
|---|---|---|
| BSE/NSE XBRL | `eqr/spine/xbrl.py` and `eqr xbrl --backfill-from` already exist, but `statements_xbrl` and `xbrl_filings` contain 0 rows; only 4 of 128,886 result-calendar rows carry an XBRL URL | Add registry discovery and resumable backfill; retain raw registry/XML, namespace/taxonomy/context/unit/basis, URL/hash, filing/revision/retrieval times and parser version; select one atomic statement basis |
| Pledge, insider and SAST events | Schemas/flags exist, but pledge, insider, named-holder, credit-rating and board-meeting inputs are empty | New versioned adapter after terms review; preserve event/dissemination/revision time, filing identity and both percentage denominators; no flag may fire on unknown denominator/date |
| Filing/concall evidence | Announcements/documents are a one-symbol pilot; `doc_sections` and `dossiers` contain 0 rows | Store hashed source artifacts with publication time and page/span evidence; deterministically verify or refuse every extracted claim |

The benchmark proposes a conservative internal source governor (one in-flight request per host,
bounded retries/backoff, circuit breaking and immutable manifests). Those controls are roadmap
requirements, not claims about exchange-published rate limits and not new commands in today's
runbook.

## Corporate-action price adjustment (derived, not a separate fetch)

Not a new source — `eqr/spine/adjust.py` reconciles the NSE corporate-actions feed above against
the tape itself, because NSE bhavcopies do **not** restate `PREV_CLOSE` on ex-dates (verified
during the build: RELIANCE's 28-Oct-2024 bonus shows prev close 2,655.70, open 1,337.00 — the tape
alone cannot label the event). The action's subject text yields a candidate factor (bonus a:b ->
b/(a+b); split X->Y -> Y/X; consolidation X->Y -> Y/X); each candidate is CONFIRMED by the ex-date
open gapping by roughly that factor (+/-35%, searched +/-3 sessions) before it is applied —
unconfirmed actions land in `factor_anomalies` and are never applied. A secondary scan catches
clean-ratio gaps (1/2, 1/5, 1/10…) persisting three sessions with a matching volume jump and no
action on file (small-cap/ETF splits missing from the NSE feed); sub-Rs 5 names are excluded as
tick artefacts. As of 2026-09-14, over 2016->2026: 707 confirmed actions + 67 gap-inferred, 44
anomalies. Rights issues and ordinary dividends are deliberately not adjusted.

## Other data-quality facts learned from the tape itself (spec §4.2)

- NSE holds weekend sessions (Budget Saturdays, Muhurat Sundays, DR-drill Saturdays) — ten found
  and loaded into `trading_days`/`holidays` rather than assumed away.
- NSE republishes Friday's `sec_bhavdata_full` under a Sunday filename in 2019-21 — the loader
  trusts the date printed **inside** the file, never the date in the URL.
- Stocks migrate between the EQ and BE/BZ series during surveillance; the price panel stays
  continuous across series while universe eligibility (spec §4.3) is judged on EQ only.

## Not yet a wired-up source

`pyproject.toml` declares a `yfinance` dependency, but as of 2026-09-14 no module under `eqr/`
calls it (verified: zero matches for `yfinance` anywhere in the package). Treat it as reserved,
not live, until a spine module actually imports it — don't assume Yahoo data backs any number in
this project today.

## Downstream (not a spine fetch, but reads or writes an external system)

| System | Direction | Notes |
|---|---|---|
| Telegram Bot API | write-only | `eqr digest --send`; send-only bot, no inbound processing |
| Anthropic (Claude Code CLI on the Mac, or API with `ANTHROPIC_API_KEY`) | writes a dossier back into `dossiers` | reads the JSON pack built from this project's own tables + documents; never reads or writes anything outside this DuckDB file |
| Backblaze B2 (via restic) | write-only | nightly backup target, not a data source |
