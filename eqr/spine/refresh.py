"""Refresh orchestrator: one trading day at a time, best-available source per date,
raw files archived immutably, every fetch logged, quality checks after."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import duckdb
import pandas as pd

from ..config import IST
from ..store import upsert, insert_rows, new_run, end_run
from . import nse_archives as na
from .adjust import refresh_factors
from .http import Http, FetchResult
from .quality import run_checks
from .universe import build_universe, store_universe

log = logging.getLogger("eqr.refresh")


def _log(con, run_id: str, res: FetchResult) -> None:
    insert_rows(con, "fetch_log", [res.log_row(run_id)])


def _fetch_prices(http: Http, d: date, con, run_id: str) -> tuple[pd.DataFrame | None, str]:
    """Best-available price file for d: UDiFF (>=2024-01-08) -> old (<=2024-07) -> sec_full."""
    attempts: list[tuple[str, str, str, str]] = []           # (label, url, raw_rel, parser)
    y = d.year
    if d >= na.UDIFF_START:
        attempts.append(("udiff", na.url_udiff(d), f"nse/udiff/{y}/BhavCopy_NSE_CM_{d:%Y%m%d}.csv.zip", "udiff"))
    if d <= na.OLD_END:
        attempts.append(("old_bhav", na.url_old_bhav(d), f"nse/bhav/{y}/cm{d:%d}{na.MONTHS[d.month-1]}{y}bhav.csv.zip", "old"))
    attempts.append(("sec_full", na.url_sec_full(d), f"nse/secfull/{y}/sec_bhavdata_full_{d:%d%m%Y}.csv", "sec_full"))
    last_status = "missing"
    for label, url, raw_rel, parser in attempts:
        res = http.get(url, source=label, key=d.isoformat(), raw_rel=raw_rel)
        _log(con, run_id, res)
        if res.ok:
            try:
                if parser == "udiff":
                    return na.parse_udiff(res.content), label
                if parser == "old":
                    return na.parse_old_bhav(res.content), label
                return na.parse_sec_full(res.text()), label
            except (na.ParseError, Exception) as e:      # noqa: BLE001 - logged, next source
                res.status, res.error = "error", f"parse: {e}"
                _log(con, run_id, res)
                last_status = "error"
                continue
        last_status = res.status if res.status != "missing" or last_status == "missing" else last_status
    return None, last_status


def load_day(con: duckdb.DuckDBPyConnection, http: Http, d: date, run_id: str,
             force: bool = False, probe_weekends: bool = True) -> dict:
    """Weekends are probed too: NSE holds special sessions on some Saturdays/Sundays
    (Union Budget days, Muhurat trading, DR-site drills); skipping them corrupts
    the PREV_CLOSE-based adjustment factors of every stock the following Monday."""
    if d.weekday() >= 5 and not probe_weekends:
        return {"date": d, "status": "weekend"}
    if not force:
        if con.execute("SELECT 1 FROM trading_days WHERE trade_date = ?", [d]).fetchone():
            return {"date": d, "status": "already_loaded"}
        if con.execute("SELECT 1 FROM holidays WHERE trade_date = ?", [d]).fetchone():
            return {"date": d, "status": "holiday"}
    prices, src = _fetch_prices(http, d, con, run_id)
    if prices is not None and not prices.empty:
        inner = pd.to_datetime(prices["trade_date"]).dt.date.mode().iloc[0]
        if inner != d:
            # NSE republishes an earlier session under a later filename (Sunday copies of
            # Friday's sec_bhavdata_full in 2019-2021). The file's own date is the truth.
            insert_rows(con, "fetch_log", [{"run_id": run_id, "source": src, "key": d.isoformat(), "status": "mismatch",
                                           "http_status": 200, "bytes": 0, "started_at": datetime.now(),
                                           "ended_at": datetime.now(), "error": f"file dated {inner}"}])
            prices, src = None, "missing"
    if prices is None:
        if src == "missing" and (date.today() - d).days >= 2:
            note = "weekend" if d.weekday() >= 5 else "no bhavcopy"
            con.execute("INSERT OR REPLACE INTO holidays VALUES (?, ?, ?)", [d, note, datetime.now()])
        return {"date": d, "status": "weekend" if (src == "missing" and d.weekday() >= 5) else src}
    if prices["deliv_pct"].isna().all():
        res = http.get(na.url_mto(d), source="mto", key=d.isoformat(),
                       raw_rel=f"nse/mto/{d.year}/MTO_{d:%d%m%Y}.DAT")
        _log(con, run_id, res)
        if res.ok:
            try:
                prices = na.merge_delivery(prices, na.parse_mto(res.text()))
            except na.ParseError as e:
                res.status, res.error = "error", str(e)
                _log(con, run_id, res)
    n = upsert(con, "prices_daily", prices)
    con.execute("INSERT OR REPLACE INTO trading_days VALUES (?, ?, ?, ?)", [d, n, src, datetime.now()])

    res = http.get(na.url_index_close(d), source="index_close", key=d.isoformat(),
                   raw_rel=f"nse/index/{d.year}/ind_close_all_{d:%d%m%Y}.csv")
    _log(con, run_id, res)
    n_idx = 0
    if res.ok:
        try:
            idx = na.parse_index_close(res.text())
            idx = idx[idx["trade_date"] == d]          # the file sometimes carries stray rows dated other days
            n_idx = upsert(con, "index_daily", idx)
        except na.ParseError as e:
            res.status, res.error = "error", str(e)
            _log(con, run_id, res)
    return {"date": d, "status": "ok", "rows": n, "source": src, "index_rows": n_idx}


def backfill(con: duckdb.DuckDBPyConnection, start: date, end: date, http: Http | None = None,
             progress_every: int = 20) -> dict:
    http = http or Http()
    run_id = new_run(con, "backfill", f"{start}..{end}")
    d, n_days, n_rows, skipped = start, 0, 0, 0
    try:
        while d <= end:
            r = load_day(con, http, d, run_id)
            if r["status"] == "ok":
                n_days += 1; n_rows += r["rows"]
                if n_days % progress_every == 0:
                    log.info("backfill %s: %d days, %d rows", d, n_days, n_rows)
                    print(f"[backfill] {d} days={n_days} rows={n_rows}", flush=True)
            elif r["status"] in ("already_loaded", "holiday", "weekend"):
                skipped += 1
            else:
                print(f"[backfill] {d} {r['status']}", flush=True)
            d += timedelta(days=1)
        end_run(con, run_id, "OK", f"days={n_days} rows={n_rows} skipped={skipped}")
    except Exception as e:                                  # noqa: BLE001
        end_run(con, run_id, "ERROR", str(e)[:400])
        raise
    return {"run_id": run_id, "days": n_days, "rows": n_rows, "skipped": skipped}


def refresh_snapshots(con: duckdb.DuckDBPyConnection, http: Http, run_id: str, d: date) -> dict:
    out: dict = {}
    stamp = d.isoformat()
    res = http.get(na.URL_EQUITY_L, source="equity_l", key=stamp, raw_rel=f"nse/snapshots/{stamp}/EQUITY_L.csv")
    _log(con, run_id, res)
    if res.ok:
        inst = na.parse_equity_l(res.text(), d)
        # keep industry from an earlier source if we have it
        old = con.execute("SELECT symbol, industry, sector, industry_source FROM instruments").df()
        if not old.empty:
            inst = inst.merge(old, on="symbol", how="left")
        out["instruments"] = upsert(con, "instruments", inst)
    res = http.get(na.URL_NIFTY500, source="nifty500_list", key=stamp, raw_rel=f"nse/snapshots/{stamp}/ind_nifty500list.csv")
    _log(con, run_id, res)
    if res.ok:
        n5 = na.parse_nifty500_list(res.text())
        for sym, ind in zip(n5.symbol, n5.industry):
            con.execute("UPDATE instruments SET industry = ?, industry_source = 'nifty500' "
                        "WHERE symbol = ? AND (industry IS NULL OR industry_source = 'nifty500')", [ind, sym])
        out["nifty500_industries"] = len(n5)
    res = http.get(na.URL_ETF_LIST, source="etf_list", key=stamp, raw_rel=f"nse/snapshots/{stamp}/eq_etfseclist.csv")
    _log(con, run_id, res)
    if res.ok:
        try:
            out["etf_list"] = upsert(con, "etf_list", na.parse_etf_list(res.text(), d))
        except na.ParseError as e:
            res.status, res.error = "error", str(e)
            _log(con, run_id, res)
    res = http.get(na.URL_FO_BAN, source="fo_ban", key=stamp, raw_rel=f"nse/snapshots/{stamp}/fo_secban.csv")
    _log(con, run_id, res)
    if res.ok:
        txt = res.text()
        import re
        m = re.search(r"Trade Date (\d{2}-[A-Z]{3}-\d{4})", txt)
        ban_date = datetime.strptime(m.group(1), "%d-%b-%Y").date() if m else d
        syms = na.parse_fo_ban(txt)
        out["fo_ban"] = upsert(con, "fo_ban", pd.DataFrame({"as_of": [ban_date] * len(syms), "symbol": syms}))
    for kind, url in (("bulk", na.URL_BULK), ("block", na.URL_BLOCK)):
        res = http.get(url, source=f"{kind}_deals", key=stamp, raw_rel=f"nse/snapshots/{stamp}/{kind}.csv")
        _log(con, run_id, res)
        if res.ok:
            try:
                out[f"{kind}_deals"] = upsert(con, "deals", na.parse_deals(res.text(), kind))
            except na.ParseError as e:
                res.status, res.error = "error", str(e)
                _log(con, run_id, res)
    return out


def latest_expected_session(now: datetime | None = None) -> date:
    """The most recent weekday whose EOD files should exist (published ~18:30-19:30 IST).
    Weekend special sessions are caught by daily_refresh probing today when it is a weekend."""
    now = now or datetime.now(IST)
    d = now.date()
    if now.hour < 19 or d.weekday() >= 5:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def daily_refresh(con: duckdb.DuckDBPyConnection, d: date | None = None, http: Http | None = None,
                  with_snapshots: bool = True, with_universe: bool = True) -> dict:
    http = http or Http()
    d = d or latest_expected_session()
    run_id = new_run(con, "daily", d.isoformat())
    summary: dict = {"run_id": run_id, "date": d}
    try:
        summary["day"] = load_day(con, http, d, run_id)
        today = datetime.now(IST).date()
        if today.weekday() >= 5 and datetime.now(IST).hour >= 19 and today != d:
            summary["weekend_probe"] = load_day(con, http, today, run_id)      # special session?
        if with_snapshots:
            summary["snapshots"] = refresh_snapshots(con, http, run_id, d)
        summary["factors"] = refresh_factors(con, start=d - timedelta(days=45))
        if with_universe and summary["day"].get("status") in ("ok", "already_loaded"):
            uni = build_universe(con, d)
            summary["universe"] = store_universe(con, uni)
        checks = run_checks(con, run_id, d)
        summary["quality_fail"] = [c["check_name"] for c in checks if c["status"] == "FAIL"]
        end_run(con, run_id, "OK" if not summary["quality_fail"] else "WARN", str(summary)[:400])
    except Exception as e:                                  # noqa: BLE001
        end_run(con, run_id, "ERROR", str(e)[:400])
        raise
    return summary
