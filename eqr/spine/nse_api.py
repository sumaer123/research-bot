"""Cookie-gated NSE endpoints -> curated tables. Each fetcher returns a DataFrame
in the target table's columns; loaders upsert and log. All are optional layers: a
403 storm degrades to a quality flag, never a crash."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

import duckdb
import pandas as pd

from ..store import upsert, insert_rows
from .http import NseApi, FetchResult

DMY = "%d-%b-%Y"          # response dates
REQ = "%d-%m-%Y"          # request query dates (the API ignores %b dates and answers "no data")


def _dt(s: Optional[str], fmt: str = DMY):
    if not s or s in ("-", ""):
        return None
    for f in (fmt, "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%B-%Y"):
        try:
            return datetime.strptime(s.strip(), f)
        except ValueError:
            continue
    return None


def _d(s: Optional[str]):
    v = _dt(s)
    return v.date() if v else None


def _month_ranges(start: date, end: date, days: int = 31):
    a = start
    while a <= end:
        b = min(a + timedelta(days=days - 1), end)
        yield a, b
        a = b + timedelta(days=1)


# ------------------------------------------------------- corporate actions --

def fetch_corporate_actions(api: NseApi, start: date, end: date, log=None) -> pd.DataFrame:
    rows = []
    for a, b in _month_ranges(start, end):
        res, js = api.get_json("/api/corporates-corporateActions",
                               {"index": "equities", "from_date": a.strftime(REQ), "to_date": b.strftime(REQ)},
                               source="nse_corp_actions", key=f"{a}..{b}")
        if log:
            log(res)
        if not isinstance(js, list):                 # the API answers a bare string on empty ranges
            continue
        for x in js:
            if not isinstance(x, dict):
                continue
            ex = _d(x.get("exDate"))
            if not ex or not x.get("symbol"):
                continue
            rows.append({"symbol": x["symbol"].strip(), "ex_date": ex, "subject": (x.get("subject") or "")[:200],
                         "record_date": _d(x.get("recDate")), "face_value": _num(x.get("faceVal")),
                         "series": x.get("series"), "fetched_at": datetime.now()})
    return pd.DataFrame(rows)


def _num(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "", "-") else None
    except ValueError:
        return None


def _xbrl_or_none(v) -> Optional[str]:
    """Normalise NSE XBRL URL: return None for missing/placeholder values.

    NSE returns "-" or a URL ending in "/-" (no filename) for pre-2018 rows
    that have no real XBRL filing. Any falsy value is also normalised to None.
    """
    if not v:
        return None
    s = str(v)
    if s == "-" or s.endswith("/-"):
        return None
    return s


# ------------------------------------------------------ results calendar ----

def fetch_financial_results(api: NseApi, start: date, end: date, log=None) -> pd.DataFrame:
    rows = []
    for a, b in _month_ranges(start, end):
        for period in ("Quarterly", "Annual"):
            res, js = api.get_json("/api/corporates-financial-results",
                                   {"index": "equities", "from_date": a.strftime(REQ),
                                    "to_date": b.strftime(REQ), "period": period},
                                   source="nse_fin_results", key=f"{period}:{a}..{b}")
            if log:
                log(res)
            if not isinstance(js, list):
                continue
            for x in js:
                if not isinstance(x, dict):
                    continue
                pe = _d(x.get("toDate"))
                if not pe and x.get("params"):
                    m = re.search(r"(\d{2}-[A-Za-z]{3}-\d{4})(\d{2}-[A-Za-z]{3}-\d{4})", x["params"])
                    pe = _d(m.group(2)) if m else None
                fd = _dt(x.get("filingDate")) or _dt(x.get("broadCastDate"))
                if not pe or not fd or not x.get("symbol"):
                    continue
                rows.append({"symbol": x["symbol"].strip(), "period_end": pe,
                             "consolidated": (x.get("consolidated") or "").strip() or "Unknown",
                             "filing_dt": fd, "audited": x.get("audited"), "period": period, "source": "nse",
                             "xbrl_url": _xbrl_or_none(x.get("xbrl")),
                             "seq_id": None,
                             "type_sub": None})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("filing_dt").drop_duplicates(subset=["symbol", "period_end", "consolidated"], keep="first")
    return df


# ------------------------------------------------------------ surveillance --

def fetch_surveillance(api: NseApi, as_of: date, log=None) -> pd.DataFrame:
    rows = []
    res, js = api.get_json("/api/reportASM", source="nse_asm", key=as_of.isoformat())
    if log:
        log(res)
    if isinstance(js, dict):
        for bucket, name in (("longterm", "ASM_LT"), ("shortterm", "ASM_ST")):
            for x in (js.get(bucket) or {}).get("data") or []:
                rows.append({"as_of": as_of, "symbol": x.get("symbol"), "list_name": name,
                             "stage": _stage(x.get("asmSurvIndicator") or x.get("survCode"))})
    res, js = api.get_json("/api/reportGSM", source="nse_gsm", key=as_of.isoformat())
    if log:
        log(res)
    if isinstance(js, list):
        for x in js:
            rows.append({"as_of": as_of, "symbol": x.get("symbol"), "list_name": "GSM",
                         "stage": _stage(x.get("gsmStage") or x.get("survCode"))})
    res, js = api.get_json("/api/reportESM", source="nse_esm", key=as_of.isoformat())
    if log:
        log(res)
    if isinstance(js, list):
        for x in js:
            rows.append({"as_of": as_of, "symbol": x.get("symbol"), "list_name": "ESM",
                         "stage": _stage(x.get("esmSurvIndicator") or x.get("survCode"))})
    df = pd.DataFrame(rows)
    return df[df.symbol.notna()] if not df.empty else df


ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}


def _stage(text) -> int:
    if not text:
        return 0
    t = str(text).upper()
    m = re.search(r"STAGE\s+([IVX]+|\d+)", t)
    if m:
        tok = m.group(1)
        return int(tok) if tok.isdigit() else ROMAN.get(tok, 0)
    m = re.search(r"-\s*([IVX]+)\s*\(", t)
    if m:
        return ROMAN.get(m.group(1), 0)
    m = re.search(r"GSM\s+(\d)", t)
    return int(m.group(1)) if m else 0


# ------------------------------------------------------------ announcements --

DOC_KINDS = (
    (re.compile(r"transcript", re.I), "transcript"),
    (re.compile(r"investor presentation|analyst.*presentation|earnings presentation", re.I), "presentation"),
    (re.compile(r"outcome of board meeting|financial result|un-?audited|audited", re.I), "results"),
    (re.compile(r"annual report", re.I), "annual_report"),
    (re.compile(r"credit rating", re.I), "rating"),
    (re.compile(r"pledge", re.I), "pledge"),
    (re.compile(r"insider trading|SAST|substantial acquisition", re.I), "insider"),
)


def classify_announcement(desc: str, text: str) -> str:
    blob = f"{desc or ''} {text or ''}"
    for rx, kind in DOC_KINDS:
        if rx.search(blob):
            return kind
    return "other"


def fetch_announcements(api: NseApi, symbol: str, log=None) -> tuple[pd.DataFrame, Optional[str]]:
    res, js = api.get_json("/api/corporate-announcements", {"index": "equities", "symbol": symbol},
                           source="nse_announcements", key=symbol)
    if log:
        log(res)
    rows, industry = [], None
    if isinstance(js, list):
        for x in js:
            dt = _dt(x.get("an_dt"))
            if not dt:
                continue
            industry = industry or x.get("smIndustry")
            rows.append({"symbol": symbol, "ann_dt": dt, "subject": (x.get("desc") or "")[:200],
                         "description": (x.get("attchmntText") or "")[:1000],
                         "attachment_url": x.get("attchmntFile") or None, "doc_id": None})
    return pd.DataFrame(rows), industry


# ------------------------------------------------------------ shareholding --

def fetch_shareholding(api: NseApi, symbol: str, log=None) -> pd.DataFrame:
    res, js = api.get_json("/api/corporate-share-holdings-master", {"index": "equities", "symbol": symbol},
                           source="nse_shareholding", key=symbol)
    if log:
        log(res)
    rows = []
    if isinstance(js, list):
        for x in js:
            pe = _d(x.get("date"))
            bd = _dt(x.get("broadcastDate"))
            if not pe:
                continue
            vis = bd.date() if bd else pe + timedelta(days=21)
            for holder, key in (("promoters", "pr_and_prgrp"), ("public", "public_val"),
                                ("employee_trusts", "employeeTrusts")):
                v = _num(x.get(key))
                if v is not None:
                    rows.append({"symbol": symbol, "period_end": pe, "holder": holder, "pct": v,
                                 "fetched_at": datetime.now(), "visible_from": vis})
    return pd.DataFrame(rows)


def fetch_annual_reports(api: NseApi, symbol: str, log=None) -> pd.DataFrame:
    res, js = api.get_json("/api/annual-reports", {"index": "equities", "symbol": symbol},
                           source="nse_annual_reports", key=symbol)
    if log:
        log(res)
    rows = []
    for x in (js or {}).get("data") or []:
        url = x.get("fileName")
        if not url:
            continue
        bd = _dt(x.get("broadcast_dttm")) or _dt(x.get("disseminationDateTime"))
        rows.append({"symbol": symbol, "kind": "annual_report", "url": url,
                     "period": f"FY{x.get('fromYr')}-{x.get('toYr')}",
                     "title": f"Annual Report FY{x.get('fromYr')}-{x.get('toYr')}",
                     "visible_from": bd.date() if bd else None})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ loaders --

def load_reference(con: duckdb.DuckDBPyConnection, api: NseApi, run_id: str, start: date, end: date,
                   as_of: Optional[date] = None) -> dict:
    """Corporate actions + results calendar for a date range, surveillance for as_of."""
    def log(res: FetchResult):
        insert_rows(con, "fetch_log", [res.log_row(run_id)])
    out = {}
    ca = fetch_corporate_actions(api, start, end, log)
    out["corporate_actions"] = upsert(con, "corporate_actions", ca)
    fr = fetch_financial_results(api, start, end, log)
    out["results_calendar"] = upsert(con, "results_calendar", fr)
    if end >= date(2025, 1, 1):
        ifr = fetch_integrated_results(api, max(start, date(2025, 1, 1)), end, log)
        # first-seen filing date wins: only fill keys the legacy feed does not have
        if not ifr.empty:
            con.register("_ifr", ifr)
            con.execute("""
                INSERT INTO results_calendar
                    (symbol, period_end, consolidated, filing_dt, audited, period, source,
                     xbrl_url, seq_id, type_sub)
                SELECT n.symbol, n.period_end, n.consolidated, n.filing_dt, n.audited,
                       n.period, n.source, n.xbrl_url, n.seq_id, n.type_sub
                FROM _ifr n
                WHERE NOT EXISTS (
                    SELECT 1 FROM results_calendar r
                    WHERE r.symbol = n.symbol AND r.period_end = n.period_end
                      AND r.consolidated = n.consolidated)""")
            con.unregister("_ifr")
            out["results_calendar_ifr"] = len(ifr)
    if as_of:
        sv = fetch_surveillance(api, as_of, log)
        out["surveillance"] = upsert(con, "surveillance", sv)
    return out


def fill_xbrl_urls(con: duckdb.DuckDBPyConnection, api: NseApi, run_id: str,
                   start: date, end: date) -> dict:
    """Re-fetch both results feeds and UPDATE results_calendar SET xbrl_url/seq_id/type_sub
    only where those columns are currently NULL. filing_dt is never touched (first-seen wins).
    Returns a dict of counts."""
    def log(res: FetchResult):
        insert_rows(con, "fetch_log", [res.log_row(run_id)])

    fr = fetch_financial_results(api, start, end, log)
    counts: dict = {"legacy_fetched": len(fr)}

    ifr = pd.DataFrame()
    if end >= date(2025, 1, 1):
        ifr = fetch_integrated_results(api, max(start, date(2025, 1, 1)), end, log)
        counts["ifr_fetched"] = len(ifr)

    # IFR rows appended after legacy — drop_duplicates keep="last" prefers IFR (has seq_id/type_sub)
    combined = pd.concat([fr, ifr], ignore_index=True) if not ifr.empty else fr.copy()
    if combined.empty:
        counts["filled"] = 0
        return counts

    # Retain only rows that carry at least one useful XBRL field
    has_xbrl = combined[
        combined["xbrl_url"].notna() | combined["seq_id"].notna() | combined["type_sub"].notna()
    ]
    useful = (has_xbrl[["symbol", "period_end", "consolidated", "xbrl_url", "seq_id", "type_sub"]]
              .drop_duplicates(subset=["symbol", "period_end", "consolidated"], keep="last")
              .copy())

    if useful.empty:
        counts["filled"] = 0
        return counts

    con.register("_xbrl_fill", useful)

    # Count rows where xbrl_url IS NULL and we have a non-null replacement ready
    n_xbrl = con.execute("""
        SELECT COUNT(*) FROM results_calendar r
        JOIN _xbrl_fill f
          ON r.symbol = f.symbol AND r.period_end = f.period_end
             AND r.consolidated = f.consolidated
        WHERE r.xbrl_url IS NULL AND f.xbrl_url IS NOT NULL
    """).fetchone()[0]

    # UPDATE: COALESCE preserves any existing non-null value; filing_dt is never in the SET list.
    # DuckDB requires fully qualified column names when both tables are in scope (FROM clause).
    con.execute("""
        UPDATE results_calendar
        SET xbrl_url = COALESCE(results_calendar.xbrl_url, f.xbrl_url),
            seq_id   = COALESCE(results_calendar.seq_id,   f.seq_id),
            type_sub = COALESCE(results_calendar.type_sub, f.type_sub)
        FROM _xbrl_fill AS f
        WHERE results_calendar.symbol       = f.symbol
          AND results_calendar.period_end   = f.period_end
          AND results_calendar.consolidated = f.consolidated
    """)

    con.unregister("_xbrl_fill")
    counts["filled"] = n_xbrl
    return counts


def load_symbol_filings(con: duckdb.DuckDBPyConnection, api: NseApi, run_id: str, symbol: str) -> dict:
    def log(res: FetchResult):
        insert_rows(con, "fetch_log", [res.log_row(run_id)])
    out = {}
    ann, industry = fetch_announcements(api, symbol, log)
    out["announcements"] = upsert(con, "announcements", ann)
    if industry:
        con.execute("UPDATE instruments SET industry = ?, industry_source = 'nse_ann' "
                    "WHERE symbol = ? AND industry IS NULL", [industry, symbol])
    out["shareholding"] = upsert(con, "shareholding", fetch_shareholding(api, symbol, log))
    return out


# --------------------------------------------- integrated filing (2025 onward) --

def fetch_integrated_results(api: NseApi, start: date, end: date, log=None, page_size: int = 500) -> pd.DataFrame:
    """NSE's post-2025 'Integrated Filing - Financials' feed, paged. Same output columns
    as fetch_financial_results; source 'nse_ifr'."""
    rows = []
    for a, b in _month_ranges(start, end):
        page = 1
        while page <= 40:
            res, js = api.get_json("/api/integrated-filing-results",
                                   {"index": "equities", "from_date": a.strftime(REQ), "to_date": b.strftime(REQ),
                                    "type": "Integrated Filing- Financials", "size": page_size, "page": page},
                                   source="nse_ifr", key=f"{a}..{b}:p{page}")
            if log:
                log(res)
            data = (js or {}).get("data") if isinstance(js, dict) else None
            if not data:
                break
            for x in data:
                if not isinstance(x, dict):
                    continue
                pe = _d(x.get("qe_Date"))
                fd = _dt(x.get("broadcast_Date")) or _dt(x.get("creation_Date"))
                if not pe or not fd or not x.get("symbol"):
                    continue
                xbrl_raw = _xbrl_or_none(x.get("xbrl")) or x.get("ixbrl")
                rows.append({"symbol": x["symbol"].strip(), "period_end": pe,
                             "consolidated": (x.get("consolidated") or "").strip() or "Unknown",
                             "filing_dt": fd, "audited": x.get("audited"), "period": "Quarterly", "source": "nse_ifr",
                             "xbrl_url": _xbrl_or_none(xbrl_raw),
                             "seq_id": x.get("seq_Id"),
                             "type_sub": x.get("type_Sub")})
            if len(data) < page_size:
                break
            page += 1
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("filing_dt").drop_duplicates(subset=["symbol", "period_end", "consolidated"], keep="first")
    return df
