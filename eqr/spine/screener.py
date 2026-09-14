"""screener.in company pages -> statements (long format) with PIT visibility.

Regex over landmark sections (section ids quarters / profit-loss / balance-sheet /
cash-flow / ratios / shareholding, ul#top-ratios, the peers sector chain). Numbers
are crores as printed. The FIRST value we ever see for a (symbol, stmt, period,
line item) is the PIT value; later differing values are kept as revisions."""
from __future__ import annotations

import calendar
import html as htmllib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import duckdb
import pandas as pd

from ..store import upsert
from .http import Http, FetchResult

BASE = "https://www.screener.in"
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")
_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
                                       "Oct", "Nov", "Dec"], start=1)}
_RATIO_KEYS = {"Market Cap": "market_cap_cr", "Current Price": "current_price", "Stock P/E": "trailing_pe",
               "Book Value": "book_value", "Dividend Yield": "dividend_yield_pct", "ROCE": "roce_pct",
               "ROE": "roe_pct"}
SECTIONS = {"quarters": "pl_q", "profit-loss": "pl_a", "balance-sheet": "bs_a", "cash-flow": "cf_a",
            "ratios": "ratios_a"}


class PageUnrecognized(ValueError):
    pass


@dataclass
class ParsedPage:
    name: str = ""
    sector: Optional[str] = None
    industry: Optional[str] = None
    meta: dict = field(default_factory=dict)
    statements: list = field(default_factory=list)     # dicts: stmt, period_end, line_item, value
    shareholding: list = field(default_factory=list)   # dicts: period_end, holder, pct
    result_pdfs: list = field(default_factory=list)    # (period_end, url)


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = htmllib.unescape(s)
    return " ".join(s.split())


def _num(s: str) -> Optional[float]:
    m = _NUM.search(s or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _period(label: str) -> Optional[date]:
    m = re.match(r"^([A-Z][a-z]{2}) (\d{4})$", label.strip())
    if not m or m.group(1) not in _MONTHS:
        return None
    y, mo = int(m.group(2)), _MONTHS[m.group(1)]
    return date(y, mo, calendar.monthrange(y, mo)[1])


def line_key(label: str) -> str:
    s = _clean(label).replace("+", " ").strip()
    s = s.replace("%", " pct ").replace("/", " ")
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", s).strip().lower()
    return re.sub(r"\s+", "_", s)


def parse_page(html: str) -> ParsedPage:
    if 'id="top-ratios"' not in (html or ""):
        raise PageUnrecognized("no top-ratios landmark")
    p = ParsedPage()
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if m:
        spans = re.findall(r"<span[^>]*>([^<]{2,120})</span>", m.group(1))
        p.name = _clean(spans[-1]) if spans else _clean(m.group(1))[:120]
    for title, attr in (("Sector", "sector"), ("Broad Industry", "industry")):
        mm = re.search(r'title="%s">\s*(.*?)\s*</a>' % title, html, re.S)
        if mm:
            setattr(p, attr, _clean(mm.group(1)))

    m = re.search(r'<ul id="top-ratios".*?</ul>', html, re.S)
    if m:
        for li in re.findall(r"<li[^>]*>(.*?)</li>", m.group(0), re.S):
            nm = re.search(r'class="name">\s*(.*?)\s*</span>', li, re.S)
            if not nm:
                continue
            name = _clean(nm.group(1))
            nums = [_num(x) for x in re.findall(r'class="number">([^<]*)<', li)]
            nums = [n for n in nums if n is not None]
            if not nums:
                continue
            if name == "High / Low" and len(nums) >= 2:
                p.meta["high_52w"], p.meta["low_52w"] = nums[0], nums[1]
            elif name in _RATIO_KEYS:
                p.meta[_RATIO_KEYS[name]] = nums[0]

    for sec, stmt in SECTIONS.items():
        ms = re.search(r'<section id="%s".*?</section>' % sec, html, re.S)
        if not ms:
            continue
        tables = re.findall(r"<table.*?</table>", ms.group(0), re.S)
        if not tables:
            continue
        p.statements += _parse_statement_table(tables[0], stmt, p)

    ms = re.search(r'<section id="shareholding".*?</section>', html, re.S)
    if ms:
        for t in re.findall(r"<table.*?</table>", ms.group(0), re.S)[:2]:     # quarterly + yearly tables
            p.shareholding += _parse_shareholding_table(t)
        seen = set()
        p.shareholding = [x for x in p.shareholding if not ((x["period_end"], x["holder"]) in seen or seen.add((x["period_end"], x["holder"])))]
    return p


def _parse_statement_table(table: str, stmt: str, p: ParsedPage) -> list[dict]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
    if not rows:
        return []
    header = [_clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], re.S)]
    periods = [_period(h) for h in header[1:]]
    out = []
    for r in rows[1:]:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
        if len(cells) < 2:
            continue
        label = _clean(cells[0])
        if label.lower().startswith("raw pdf"):
            for pe, cell in zip(periods, cells[1:]):
                mm = re.search(r'href="([^"]+)"', cell, re.I)
                if pe and mm:
                    href = htmllib.unescape(mm.group(1))
                    p.result_pdfs.append((pe, href if href.startswith("http") else BASE + href))
            continue
        key = line_key(label)
        if not key:
            continue
        for pe, cell in zip(periods, cells[1:]):
            if pe is None:
                continue
            v = _num(_clean(cell))
            if v is None:
                continue
            out.append({"stmt": stmt, "period_end": pe, "line_item": key, "value": v})
    return out


def _parse_shareholding_table(table: str) -> list[dict]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
    if not rows:
        return []
    header = [_clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], re.S)]
    periods = [_period(h) for h in header[1:]]
    out = []
    for r in rows[1:]:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
        if len(cells) < 2:
            continue
        label = _clean(cells[0]).replace("+", "").strip().lower()
        holder = {"promoters": "promoters", "fiis": "fii", "diis": "dii", "government": "government",
                  "public": "public", "no. of shareholders": "n_shareholders", "others": "others"}.get(label)
        if not holder:
            continue
        for pe, cell in zip(periods, cells[1:]):
            v = _num(_clean(cell))
            if pe and v is not None:
                out.append({"period_end": pe, "holder": holder, "pct": v})
    return out


# ----------------------------------------------------------------- fetch ----

def fetch_page(http: Http, symbol: str, as_of: Optional[date] = None) -> tuple[FetchResult, str]:
    """Consolidated first, standalone fallback. Raw HTML archived per (symbol, day, basis)."""
    as_of = as_of or date.today()
    last = None
    for basis, path in (("consolidated", f"/company/{symbol}/consolidated/"), ("standalone", f"/company/{symbol}/")):
        res = http.get(BASE + path, source="screener", key=f"{symbol}:{basis}",
                       raw_rel=f"screener/{symbol}/{as_of.isoformat()}_{basis}.html",
                       headers={"Accept": "text/html"})
        last = res
        if res.ok and 'id="top-ratios"' in res.text():
            if basis == "consolidated" and _looks_empty(res.text()):
                continue
            return res, basis
        if res.status == "blocked":
            return res, basis
    return last, "none"


def _looks_empty(html: str) -> bool:
    """A consolidated view with no period columns (standalone-only reporters) is empty."""
    m = re.search(r'<section id="profit-loss".*?</section>', html, re.S)
    if not m:
        return True
    head = re.search(r"<thead>.*?</thead>", m.group(0), re.S)
    return not head or len(re.findall(r"<th(?:\s[^>]*)?>", head.group(0))) < 2     # not <thead>


# --------------------------------------------------------------- loaders ----

def visible_from_for(period_end: date, stmt: str, filing: Optional[date]) -> date:
    if filing:
        return filing
    if stmt == "pl_q":
        return period_end + timedelta(days=60 if period_end.month == 3 else 45)
    return period_end + timedelta(days=60)


def load_parsed(con: duckdb.DuckDBPyConnection, symbol: str, basis: str, page: ParsedPage,
                fetched_at: Optional[datetime] = None) -> dict:
    fetched_at = fetched_at or datetime.now()
    out = {"statements_new": 0, "revisions": 0, "shareholding": 0}
    if page.statements:
        df = pd.DataFrame(page.statements)
        df.insert(0, "symbol", symbol)
        df.insert(1, "basis", basis)
        df["fetched_at"] = fetched_at
        cal = con.execute("SELECT period_end, min(filing_dt) AS filing_dt FROM results_calendar "
                          "WHERE symbol = ? GROUP BY period_end", [symbol]).df()
        filing = {pd.Timestamp(r.period_end).date(): pd.Timestamp(r.filing_dt).date() for r in cal.itertuples()}
        df["visible_from"] = [visible_from_for(pe, st, filing.get(pe)) for pe, st in zip(df.period_end, df.stmt)]
        con.register("_scr_new", df)
        out["revisions"] = _count_revisions(con)
        con.execute("""
            INSERT INTO statements
            SELECT n.symbol, n.basis, n.stmt, n.period_end, n.line_item, n.value, n.fetched_at, n.visible_from
            FROM _scr_new n WHERE NOT EXISTS (
              SELECT 1 FROM statements s WHERE s.symbol = n.symbol AND s.basis = n.basis AND s.stmt = n.stmt
                AND s.period_end = n.period_end AND s.line_item = n.line_item)
        """)
        out["statements_new"] = con.execute("SELECT count(*) FROM _scr_new n WHERE n.fetched_at = ? AND EXISTS "
                                            "(SELECT 1 FROM statements s WHERE s.symbol = n.symbol AND s.fetched_at = ?)",
                                            [fetched_at, fetched_at]).fetchone()[0]
        con.unregister("_scr_new")
    if page.shareholding:
        sh = pd.DataFrame(page.shareholding)
        sh.insert(0, "symbol", symbol)
        sh["fetched_at"] = fetched_at
        sh["visible_from"] = [pe + timedelta(days=21) for pe in sh.period_end]
        # NSE-sourced rows (with real broadcast dates) win: only insert missing keys
        con.register("_scr_sh", sh)
        con.execute("""INSERT INTO shareholding SELECT symbol, period_end, holder, pct, fetched_at, visible_from
                       FROM _scr_sh n WHERE NOT EXISTS (SELECT 1 FROM shareholding s WHERE s.symbol = n.symbol
                       AND s.period_end = n.period_end AND s.holder = n.holder)""")
        con.unregister("_scr_sh")
        out["shareholding"] = len(sh)
    meta = dict(page.meta)
    meta.update({"symbol": symbol, "basis": basis, "industry": page.industry, "sector": page.sector,
                 "fetched_at": fetched_at})
    upsert(con, "screener_meta", pd.DataFrame([meta]))
    if page.industry:
        con.execute("UPDATE instruments SET industry = ?, sector = ?, industry_source = 'screener' "
                    "WHERE symbol = ? AND (industry IS NULL OR industry_source IN ('nse_ann'))",
                    [page.industry, page.sector, symbol])
    return out


def _count_revisions(con) -> int:
    n = con.execute("""
        SELECT count(*) FROM _scr_new n JOIN statements s
          ON s.symbol = n.symbol AND s.basis = n.basis AND s.stmt = n.stmt
         AND s.period_end = n.period_end AND s.line_item = n.line_item
        WHERE s.value IS DISTINCT FROM n.value""").fetchone()[0]
    if n:
        con.execute("""
            INSERT OR IGNORE INTO statement_revisions
            SELECT n.symbol, n.basis, n.stmt, n.period_end, n.line_item, n.value, n.fetched_at
            FROM _scr_new n JOIN statements s
              ON s.symbol = n.symbol AND s.basis = n.basis AND s.stmt = n.stmt
             AND s.period_end = n.period_end AND s.line_item = n.line_item
            WHERE s.value IS DISTINCT FROM n.value""")
    return n


def sweep(con: duckdb.DuckDBPyConnection, http: Http, symbols: list[str], run_id: str,
          as_of: Optional[date] = None, log=None) -> dict:
    ok, blocked, missing, errors = 0, 0, 0, 0
    for sym in symbols:
        res, basis = fetch_page(http, sym, as_of)
        if log:
            log(res)
        if res.status == "blocked":
            blocked += 1
            if blocked >= 5:
                break
            continue
        if not res.ok or basis == "none":
            missing += 1
            continue
        try:
            page = parse_page(res.text())
            load_parsed(con, sym, basis, page, datetime.now())
            ok += 1
        except (PageUnrecognized, Exception) as e:      # noqa: BLE001
            errors += 1
            res.status, res.error = "error", f"parse/load: {e}"
            if log:
                log(res)
    return {"ok": ok, "blocked": blocked, "missing": missing, "errors": errors}


def load_raw_dir(con: duckdb.DuckDBPyConnection, raw_dir, symbols: Optional[list[str]] = None) -> dict:
    """Parse archived HTML (fetched without a DB) and load it. Consolidated preferred per day."""
    from pathlib import Path
    root = Path(raw_dir) / "screener"
    n, errs = 0, 0
    for symdir in sorted(root.iterdir()) if root.exists() else []:
        sym = symdir.name
        if symbols and sym not in symbols:
            continue
        files = sorted(symdir.glob("*.html"))
        by_day: dict[str, dict[str, Path]] = {}
        for f in files:
            day, basis = f.stem.rsplit("_", 1)
            by_day.setdefault(day, {})[basis] = f
        for day, d in sorted(by_day.items()):
            basis = "consolidated" if "consolidated" in d else "standalone"
            html = d[basis].read_text(errors="replace")
            if basis == "consolidated" and (_looks_empty(html) or 'id="top-ratios"' not in html):
                if "standalone" in d:
                    basis, html = "standalone", d["standalone"].read_text(errors="replace")
            try:
                page = parse_page(html)
                load_parsed(con, sym, basis, page, datetime.strptime(day, "%Y-%m-%d"))
                n += 1
            except Exception:                            # noqa: BLE001
                errs += 1
    return {"loaded": n, "errors": errs}


def sync_visibility(con: duckdb.DuckDBPyConnection) -> int:
    """Re-stamp statements with the real filing date wherever results_calendar knows one
    (earlier or later than the rule): the truth wins in both directions."""
    n = con.execute("""
        WITH f AS (SELECT symbol, period_end, min(filing_dt)::DATE AS fd FROM results_calendar GROUP BY 1, 2)
        SELECT count(*) FROM statements s JOIN f USING (symbol, period_end) WHERE s.visible_from <> f.fd
    """).fetchone()[0]
    con.execute("""
        UPDATE statements SET visible_from = f.fd
        FROM (SELECT symbol, period_end, min(filing_dt)::DATE AS fd FROM results_calendar GROUP BY 1, 2) f
        WHERE statements.symbol = f.symbol AND statements.period_end = f.period_end AND statements.visible_from <> f.fd
    """)
    return n
