"""eqr command line."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

import typer

app = typer.Typer(help="Sumaer Research Bot (eqr)", no_args_is_help=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def _d(s: Optional[str]) -> Optional[date]:
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


@app.command()
def init():
    """Create the data directory and schema."""
    from .store import connect
    con = connect()
    con.close()
    from .config import settings
    typer.echo(f"initialised {settings().db_path}")


@app.command()
def refresh(date_: Optional[str] = typer.Option(None, "--date", help="YYYY-MM-DD (default: latest expected session)"),
            backfill_from: Optional[str] = typer.Option(None, "--backfill-from"),
            backfill_to: Optional[str] = typer.Option(None, "--backfill-to"),
            no_snapshots: bool = typer.Option(False, "--no-snapshots"),
            no_universe: bool = typer.Option(False, "--no-universe")):
    """Load EOD data. With --backfill-from, load every session in the range."""
    from .store import connect
    from .spine.refresh import daily_refresh, backfill
    con = connect()
    try:
        if backfill_from:
            out = backfill(con, _d(backfill_from), _d(backfill_to) or date.today())
        else:
            out = daily_refresh(con, _d(date_), with_snapshots=not no_snapshots, with_universe=not no_universe)
        typer.echo(json.dumps(out, default=str, indent=1))
    finally:
        con.close()


@app.command()
def factors(start: Optional[str] = typer.Option(None, "--from")):
    """Detect split/bonus adjustment factors from PREV_CLOSE restatements."""
    from .store import connect
    from .spine.adjust import refresh_factors
    con = connect()
    try:
        typer.echo(f"adj_factors upserted: {refresh_factors(con, start=_d(start))}")
    finally:
        con.close()


@app.command()
def universe(as_of: Optional[str] = typer.Option(None, "--as-of"),
             monthly_from: Optional[str] = typer.Option(None, "--monthly-from", help="build every month-end from this date")):
    """Build the PIT liquidity universe for a date (or every month-end since --monthly-from)."""
    from .store import connect
    from .spine.universe import build_universe, store_universe, month_end_sessions
    con = connect()
    try:
        if monthly_from:
            dates = month_end_sessions(con, _d(monthly_from), _d(as_of) or date.today())
        else:
            last = con.execute("SELECT max(trade_date) FROM trading_days WHERE trade_date <= ?",
                               [_d(as_of) or date.today()]).fetchone()[0]
            dates = [last] if last else []
        for d in dates:
            n = store_universe(con, build_universe(con, d))
            typer.echo(f"{d}: {n} names")
    finally:
        con.close()


@app.command()
def doctor():
    """Live smoke test: one fetch per source, schema check, row counts."""
    from .store import connect
    from .spine.http import Http, NseApi
    from .spine import nse_archives as na
    from .spine.refresh import latest_expected_session
    d = latest_expected_session()
    http = Http(rate_limit_s=0.5)
    checks = []
    for label, url in (("index_close", na.url_index_close(d)), ("equity_l", na.URL_EQUITY_L),
                       ("fo_ban", na.URL_FO_BAN), ("udiff", na.url_udiff(d))):
        r = http.get(url, source=label, key="doctor")
        checks.append((label, r.status, r.http_status, r.bytes))
    api = NseApi(http)
    r, js = api.get_json("/api/reportASM", source="nse_api", key="doctor")
    checks.append(("nse_api_asm", r.status, r.http_status, r.bytes))
    con = connect()
    try:
        for t in ("prices_daily", "trading_days", "index_daily", "statements", "features", "ranks"):
            n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            checks.append((f"rows:{t}", "ok", None, n))
    finally:
        con.close()
    for c in checks:
        typer.echo(f"{c[0]:<22} {c[1]:<8} {c[2] or '':<5} {c[3]}")



@app.command()
def fundamentals(symbols: Optional[str] = typer.Option(None, "--symbols", help="comma-separated; default: EQ universe"),
                 fetch_only: bool = typer.Option(False, "--fetch-only", help="archive HTML only, no DB (safe while a writer holds the DB)"),
                 load_raw: bool = typer.Option(False, "--load-raw", help="parse archived HTML into the DB"),
                 rate: float = typer.Option(1.5, "--rate", help="seconds between screener requests"),
                 limit: int = typer.Option(0, "--limit")):
    """screener.in statements sweep: fetch, load, or both."""
    from .config import settings
    from .spine.http import Http
    from .spine import screener as sc
    from .spine import nse_archives as na
    s = settings()
    if symbols:
        syms = [x.strip().upper() for x in symbols.split(",") if x.strip()]
    else:
        snaps = sorted((s.raw_dir / "nse" / "snapshots").glob("*/EQUITY_L.csv"))
        if not snaps:
            raise typer.BadParameter("no EQUITY_L snapshot; run `eqr refresh` first")
        inst = na.parse_equity_l(snaps[-1].read_text())
        syms = sorted(inst[inst.series == "EQ"].symbol.tolist())
    if limit:
        syms = syms[:limit]
    http = Http(rate_limit_s=rate)
    if fetch_only:
        ok = blocked = miss = 0
        for i, sym in enumerate(syms, 1):
            res, basis = sc.fetch_page(http, sym)
            if res.status == "blocked":
                blocked += 1
                typer.echo(f"[{i}/{len(syms)}] {sym} BLOCKED")
                if blocked >= 5:
                    typer.echo("5 blocks in a row; stopping")
                    break
            elif res.ok and basis != "none":
                ok += 1; blocked = 0
            else:
                miss += 1
            if i % 50 == 0:
                typer.echo(f"[{i}/{len(syms)}] ok={ok} missing={miss}", err=False)
        typer.echo(json.dumps({"ok": ok, "missing": miss, "blocked": blocked}))
        return
    from .store import connect, new_run, end_run, insert_rows
    con = connect()
    try:
        if load_raw:
            out = sc.load_raw_dir(con, s.raw_dir, syms if symbols else None)
            out["visibility_restamped"] = sc.sync_visibility(con)
            typer.echo(json.dumps(out))
            return
        run_id = new_run(con, "fundamentals", f"{len(syms)} symbols")
        out = sc.sweep(con, http, syms, run_id, log=lambda r: insert_rows(con, "fetch_log", [r.log_row(run_id)]))
        end_run(con, run_id, "OK", json.dumps(out))
        typer.echo(json.dumps(out))
    finally:
        con.close()


@app.command()
def reference(start: str = typer.Option("2016-01-01", "--from"), end: Optional[str] = typer.Option(None, "--to"),
              no_surveillance: bool = typer.Option(False, "--no-surveillance"),
              xbrl_urls_from: Optional[str] = typer.Option(None, "--xbrl-urls-from",
                                                            help="YYYY-MM-DD: fill NULL xbrl_url from this date to today")):
    """NSE cookie-gated reference data: corporate actions, results filing dates, surveillance lists."""
    from .store import connect, new_run, end_run
    from .spine.http import Http, NseApi
    from .spine.nse_api import load_reference, fill_xbrl_urls
    from .spine.refresh import latest_expected_session
    con = connect()
    api = NseApi(Http(rate_limit_s=0.8))
    run_id = new_run(con, "reference", f"{start}..{end}")
    try:
        out = load_reference(con, api, run_id, _d(start), _d(end) or date.today(),
                             as_of=None if no_surveillance else latest_expected_session())
        if xbrl_urls_from:
            out["fill_xbrl"] = fill_xbrl_urls(con, api, run_id, _d(xbrl_urls_from), date.today())
        from .spine.screener import sync_visibility
        out["visibility_restamped"] = sync_visibility(con)
        end_run(con, run_id, "OK", json.dumps(out))
        typer.echo(json.dumps(out))
    except Exception as e:
        end_run(con, run_id, "ERROR", str(e)[:400])
        raise
    finally:
        con.close()


@app.command()
def features(as_of: Optional[str] = typer.Option(None, "--as-of"),
             monthly_from: Optional[str] = typer.Option(None, "--monthly-from"),
             regime: bool = typer.Option(True, "--regime/--no-regime")):
    """Build the feature table for a date (or every month-end since --monthly-from)."""
    from .store import connect
    from .features.build import build_features
    from .features.panel import load_panel, window_start
    from .spine.universe import month_end_sessions
    from .strategy.regime import store_regime
    con = connect()
    try:
        end = _d(as_of) or con.execute("SELECT max(trade_date) FROM trading_days").fetchone()[0]
        if monthly_from:
            dates = month_end_sessions(con, _d(monthly_from), end)
        else:
            dates = [con.execute("SELECT max(trade_date) FROM trading_days WHERE trade_date <= ?", [end]).fetchone()[0]]
        panel = load_panel(con, window_start(dates[0], 420), dates[-1], series=("EQ", "BE", "BZ"))
        for d in dates:
            f = build_features(con, d, panel=panel)
            typer.echo(f"{d}: {len(f)} names, rankable {int(f['rankable'].sum()) if len(f) else 0}")
        if regime:
            typer.echo(f"regime rows: {store_regime(con)}")
    finally:
        con.close()


@app.command()
def rank(sleeve: str = typer.Option("L", "--sleeve"), as_of: Optional[str] = typer.Option(None, "--as-of"),
         top: Optional[int] = typer.Option(None, "--top", help="override N (default: the validated run's choice)"),
         variant: Optional[str] = typer.Option(None, "--variant", help="override weights variant")):
    """Rank a sleeve on the latest (or given) feature date with the configuration the latest
    walk-forward run selected; store the list."""
    from .store import connect
    from .strategy.rank import rank_sleeve, validated_config
    from .strategy.sleeves import SleeveConfig
    con = connect()
    try:
        d = _d(as_of) or con.execute("SELECT max(as_of) FROM features").fetchone()[0]
        cfg, verdict = validated_config(con, sleeve.upper())
        if top or variant:
            mk = SleeveConfig.L if sleeve.upper() == "L" else SleeveConfig.S
            cfg = mk(top_n=top or cfg.top_n, variant=variant or cfg.variant)
        tbl = rank_sleeve(con, cfg, d)
        held = tbl[tbl.weight > 0]
        typer.echo(f"{sleeve} as of {d}: config N{cfg.top_n} {cfg.variant} (last verdict {verdict}), "
                   f"regime {tbl.regime.iloc[0] if len(tbl) else '?'}, universe {tbl.universe_size.iloc[0] if len(tbl) else 0}")
        for r in held.itertuples():
            typer.echo(f"{r.rank:>4} {r.symbol:<14} score {r.score:+.3f} weight {r.weight:.3f}")
    finally:
        con.close()


@app.command()
def backtest(sleeve: str = typer.Option("L", "--sleeve"), start: str = typer.Option("2017-01-01", "--start"),
             end: Optional[str] = typer.Option(None, "--end"), capital: float = typer.Option(1_000_000, "--capital"),
             top: int = typer.Option(30, "--top"), variant: str = typer.Option("base", "--variant"),
             zero_brokerage: bool = typer.Option(False, "--zero-brokerage")):
    """Single backtest of one sleeve configuration; writes a report."""
    from .store import connect, new_run, end_run
    from .strategy.sleeves import SleeveConfig
    from .validate.backtest import BacktestConfig, run_backtest
    from .validate.costs import DISCOUNT_BROKER, ZERO_BROKERAGE
    from .validate.report import write_backtest_report
    con = connect()
    try:
        e = _d(end) or con.execute("SELECT max(trade_date) FROM trading_days").fetchone()[0]
        sl = SleeveConfig.L(top_n=top, variant=variant) if sleeve.upper() == "L" else SleeveConfig.S(top_n=top, variant=variant)
        cfg = BacktestConfig(sleeve=sl, start=_d(start), end=e, capital=capital,
                             costs=ZERO_BROKERAGE if zero_brokerage else DISCOUNT_BROKER)
        run_id = new_run(con, "backtest", f"{sleeve} {start}..{e}")
        res = run_backtest(con, cfg, progress=lambda m: typer.echo(m, err=True))
        path = write_backtest_report(con, res, run_id, f"Backtest — Sleeve {sleeve.upper()} N={top} {variant}")
        from .validate.trials import log_backtest
        log_backtest(res.config, run_id, purpose="exploratory", report_path=path)
        end_run(con, run_id, "OK", str(path))
        typer.echo((path / "report.md").read_text())
    finally:
        con.close()


@app.command()
def validate(sleeve: str = typer.Option("L", "--sleeve"), start: str = typer.Option("2017-01-01", "--start"),
             end: Optional[str] = typer.Option(None, "--end"), holdout_start: str = typer.Option("2025-09-01", "--holdout-start"),
             capital: float = typer.Option(1_000_000, "--capital"), first_fold_year: int = typer.Option(2019, "--first-fold-year"),
             purpose: str = typer.Option("protocol", "--purpose", help="exploratory|protocol|repair (trial ledger)")):
    """Pre-registered walk-forward validation with the acceptance bar; writes a report."""
    from .store import connect, new_run, end_run
    from .validate.walkforward import WalkForwardConfig, run_walk_forward, _key
    from .validate.report import write_walkforward_report
    from .validate.trials import prior_distinct_trials, log_walkforward
    con = connect()
    try:
        e = _d(end) or con.execute("SELECT max(trade_date) FROM trading_days").fetchone()[0]
        hs = _d(holdout_start)
        years = list(range(first_fold_year, hs.year + 1))
        wf = WalkForwardConfig(sleeve=sleeve.upper(), start=_d(start), end=e, holdout_start=hs, fold_years=years, capital=capital)
        grid_keys = [_key(c) for c in wf.grid]
        wf.prior_trials = prior_distinct_trials(sleeve.upper(), exclude=grid_keys)
        run_id = new_run(con, "validate", f"{sleeve} {start}..{e}")
        out = run_walk_forward(con, wf, progress=lambda m: typer.echo(m, err=True))
        path = write_walkforward_report(con, out, run_id)
        log_walkforward(out, run_id, purpose=purpose, report_path=path)
        end_run(con, run_id, out["acceptance"]["verdict"], str(path))
        typer.echo((path / "report.md").read_text())
    finally:
        con.close()


@app.command()
def trials(seed: bool = typer.Option(False, "--seed", help="backfill the ledger from data/reports/ (purpose=repair)"),
           sleeve: str = typer.Option("L", "--sleeve")):
    """Show or seed the append-only trial ledger (true multiple-testing count)."""
    from .validate import trials as tr
    if seed:
        typer.echo(json.dumps(tr.seed_from_reports()))
        return
    s = sleeve.upper()
    rows = tr.read_trials(s)
    typer.echo(f"{s}: {len(rows)} runs · {len(tr.distinct_keys(s))} distinct configs")
    for t in rows:
        typer.echo(f"  {t.get('ts')} {t.get('purpose'):<11} n_grid={t.get('n_grid')} {t.get('run_id')}")


@app.command()
def web(host: Optional[str] = typer.Option(None, "--host"), port: Optional[int] = typer.Option(None, "--port")):
    """Serve the dashboard and advisor API."""
    import uvicorn
    from .config import settings
    s = settings()
    uvicorn.run("eqr.surfaces.web.app:app", host=host or s.web_host, port=port or s.web_port, log_level="info")


@app.command()
def digest(send: bool = typer.Option(False, "--send", help="actually send to Telegram (default prints)")):
    """Build (and optionally send) the daily Telegram digest."""
    from .surfaces.queries import open_ro
    from .surfaces.digest import build_digest
    from .surfaces.telegram import send as tg_send
    con = open_ro()
    try:
        text = build_digest(con)
    finally:
        con.close()
    typer.echo(text)
    if send:
        typer.echo(json.dumps(tg_send(text)))


@app.command()
def xbrl(backfill_from: Optional[str] = typer.Option(None, "--backfill-from",
                                                       help="sweep all calendar rows with period_end >= DATE"),
         recent: Optional[int] = typer.Option(None, "--recent",
                                               help="only filings from the last N days"),
         symbols: Optional[str] = typer.Option(None, "--symbols", help="comma-separated"),
         limit: int = typer.Option(0, "--limit"),
         rate: Optional[float] = typer.Option(None, "--rate",
                                              help="seconds between requests (default: EQR_RATE_LIMIT_S)")):
    """Download, archive, and parse XBRL filings from results_calendar."""
    from .store import connect, new_run, end_run, insert_rows
    from .spine.http import Http
    from .spine.xbrl import sweep_xbrl
    from .config import settings

    s = settings()
    rate_s = rate if rate is not None else s.rate_limit_s
    con = connect()
    http = Http(rate_limit_s=rate_s)
    run_id = new_run(con, "xbrl_sweep", f"backfill_from={backfill_from} recent={recent} symbols={symbols}")
    try:
        where_clauses = ["rc.xbrl_url IS NOT NULL"]
        params: list = []

        if symbols:
            sym_list = [x.strip().upper() for x in symbols.split(",") if x.strip()]
            placeholders = ",".join(["?"] * len(sym_list))
            where_clauses.append(f"rc.symbol IN ({placeholders})")
            params.extend(sym_list)

        if backfill_from:
            where_clauses.append("rc.period_end >= ?")
            params.append(_d(backfill_from))

        if recent is not None:
            where_clauses.append(f"rc.period_end >= current_date - INTERVAL {recent} DAY")

        where_sql = " AND ".join(where_clauses)

        # Prioritise annual/half-yearly (audited=Yes is a good proxy for FY/H)
        # then chronological oldest-first so the most informative filings load first
        sql = f"""
            SELECT rc.symbol,
                   rc.period_end,
                   CASE rc.consolidated WHEN 'Consolidated' THEN 'C' ELSE 'S' END AS basis,
                   rc.xbrl_url,
                   rc.filing_dt
            FROM results_calendar rc
            WHERE {where_sql}
            ORDER BY
                CASE WHEN UPPER(COALESCE(rc.audited, '')) = 'YES' THEN 0 ELSE 1 END ASC,
                rc.period_end ASC
        """
        rows_raw = con.execute(sql, params).fetchall()
        if limit:
            rows_raw = rows_raw[:limit]

        typer.echo(f"rows to sweep: {len(rows_raw)}")
        out = sweep_xbrl(con, http, rows_raw, run_id)
        end_run(con, run_id, "OK", json.dumps(out))
        typer.echo(json.dumps(out))
    except Exception as e:
        end_run(con, run_id, "ERROR", str(e)[:400])
        raise
    finally:
        con.close()


@app.command()
def filings(symbols: str = typer.Argument(..., help="comma-separated symbols"), docs: bool = typer.Option(True, "--docs/--no-docs")):
    """NSE announcements + shareholding for symbols; download filing PDFs into the document store."""
    from .store import connect, new_run, end_run, insert_rows
    from .spine.http import Http, NseApi
    from .spine.nse_api import load_symbol_filings
    from .research.docstore import sync_symbol_documents
    con = connect()
    api = NseApi(Http(rate_limit_s=1.0))
    run_id = new_run(con, "filings", symbols)
    try:
        for sym in [x.strip().upper() for x in symbols.split(",") if x.strip()]:
            out = load_symbol_filings(con, api, run_id, sym)
            if docs:
                out["documents"] = sync_symbol_documents(con, api, sym, log=lambda r: insert_rows(con, "fetch_log", [r.log_row(run_id)]))
            typer.echo(f"{sym}: {json.dumps(out)}")
        end_run(con, run_id, "OK")
    finally:
        con.close()


@app.command()
def pack(symbol: str, as_of: Optional[str] = typer.Option(None, "--as-of")):
    """Write the dossier pack (JSON + excerpts) for a symbol."""
    from .store import connect
    from .research.pack import build_pack
    con = connect()
    try:
        p = build_pack(con, symbol.upper(), _d(as_of))
        typer.echo(f"pack at {p['_path']} · documents {len(p['documents'])} · quarterly periods {len(p['quarterly'])}")
    finally:
        con.close()


@app.command()
def dossier(symbol: str, as_of: Optional[str] = typer.Option(None, "--as-of"), model: Optional[str] = typer.Option(None, "--model"),
            dry_run: bool = typer.Option(False, "--dry-run", help="build the pack and prompt only")):
    """Run a Claude research dossier for a symbol (validated, cited, stored)."""
    from .store import connect
    from .research.dossier import run_dossier
    con = connect()
    try:
        typer.echo(json.dumps(run_dossier(con, symbol.upper(), _d(as_of), model=model, dry_run=dry_run), indent=1))
    finally:
        con.close()


if __name__ == "__main__":
    app()
