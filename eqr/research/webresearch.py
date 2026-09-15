"""Web-research fan-out: three independent facets per symbol, searched in parallel through the
anonymous Parallel MCP, filtered/deduped/fetched by pure helpers, harvested into web_sources /
news_items, and exposed to the dossier pack. Wave-1 doctrine: this enriches dossier TEXT only —
it never feeds rating/rank/score, and it never raises (fail-soft, like advisor_client).

Only the orchestrator thread touches DuckDB; each worker owns its own MCP session and output
file (graph-of-loops worker isolation)."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd

from ..config import settings
from ..store import upsert
from .parallel_client import McpClient, RateLimiter

log = logging.getLogger("eqr.webresearch")

_NAME_STOP = {"limited", "ltd", "ltd.", "limited.", "pvt", "private"}


@dataclass
class Facet:
    name: str
    objective: str
    queries: list[str]
    lookback_days: int


@dataclass
class FacetResult:
    facet: str
    ok: bool
    sources: list[dict] = field(default_factory=list)
    calls: int = 0


# ---------------- pure helpers ----------------

def _short_name(name: Optional[str], n: int = 3) -> str:
    toks = [t for t in (name or "").split() if t.lower().strip(".") not in _NAME_STOP]
    return " ".join(toks[:n]) or (name or "").strip()


def _clamp(text: str, symbol: str, lo: int = 3, hi: int = 6) -> str:
    w = text.split()
    if len(w) > hi:
        w = w[:hi]
    while len(w) < lo:
        w.append(symbol)
    return " ".join(w)


def facet_specs(symbol: str, name: Optional[str], industry: Optional[str],
                as_of: date) -> list[Facet]:
    """The three independent facets, worded after upx-research SKILL §3. Each is built ONLY from
    (symbol, name, industry, as_of): no facet consumes another's output (the fake-edge test)."""
    nm = _short_name(name, 3) or symbol
    ind = _short_name(industry, 2) if industry else "Indian"
    return [
        Facet("results",
              f"Latest quarterly results, revenue and profit growth and management commentary "
              f"for {name or symbol} (NSE: {symbol})",
              [_clamp(f"{nm} quarterly results", symbol),
               _clamp(f"{nm} revenue profit growth", symbol),
               _clamp(f"{symbol} results guidance outlook", symbol)],
              lookback_days=90),
        Facet("actions",
              f"Corporate actions and governance events for {name or symbol} (NSE: {symbol}): "
              f"promoter pledge or stake change, SEBI or exchange action, rating change, board "
              f"or auditor exit, M&A, large orders",
              [_clamp(f"{nm} promoter pledge stake", symbol),
               _clamp(f"{nm} SEBI rating action", symbol),
               _clamp(f"{symbol} board auditor change", symbol)],
              lookback_days=180),
        Facet("sector",
              f"Sector outlook and peer comparison for {name or symbol} in the Indian {ind} "
              f"sector: demand trends, margin pressure, and how peers are priced",
              [_clamp(f"{nm} sector outlook demand", symbol),
               _clamp(f"{ind} sector peers valuation", symbol),
               _clamp(f"{nm} peer comparison margins", symbol)],
              lookback_days=120),
    ]


def allowed_host(url: str, allowed_domains: tuple[str, ...]) -> bool:
    if not allowed_domains:
        return True                                   # empty = allow all (no client-side filter)
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def within_lookback(publish_date: Optional[str], as_of: Optional[date],
                    lookback_days: int) -> tuple[bool, bool]:
    """(keep, flagged). Undated or unparseable results are KEPT but flagged; anything older than
    the window, or published after as_of (a PIT violation), is dropped."""
    if not publish_date:
        return True, True
    try:
        d = date.fromisoformat(str(publish_date)[:10])
    except ValueError:
        return True, True
    if as_of and d > as_of:
        return False, False
    if as_of and d < as_of - timedelta(days=lookback_days):
        return False, False
    return True, False


def canonical_url(url: str) -> str:
    """Drop utm_* params and the fragment; keep everything else (a stable dedup / id key)."""
    p = urlparse(url)
    params = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
              if not k.lower().startswith("utm_")]
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(params), ""))


def src_id_for(symbol: str, url: str) -> str:
    h = hashlib.sha1(canonical_url(url).encode()).hexdigest()[:10]
    return f"{symbol}-w{h}"


# ---------------- worker (no DB, own MCP session + own file) ----------------

def run_facet(client, facet: Facet, symbol: str, as_of: date, *,
              allowed_domains: tuple[str, ...], lookback_days: int, fetch_top_k: int,
              web_dir: Path) -> FacetResult:
    """Search -> client-side domain + lookback filter -> dedupe -> fetch top-K -> write <facet>.json.
    Never raises; never touches DuckDB."""
    try:
        results = client.web_search(facet.objective, facet.queries)
    except Exception as e:                              # defence in depth; client is already fail-soft
        log.warning("web_search raised for %s/%s: %s", symbol, facet.name, e)
        results = None
    if results is None:
        return FacetResult(facet.name, False, [], getattr(client, "calls_made", 0))

    kept: list[tuple] = []
    seen: set[str] = set()
    for r in results:
        if not allowed_host(r.url, allowed_domains):
            continue
        keep, flagged = within_lookback(r.publish_date, as_of, lookback_days)
        if not keep:
            continue
        sid = src_id_for(symbol, r.url)
        if sid in seen:
            continue
        seen.add(sid)
        kept.append((r, canonical_url(r.url), sid, flagged))

    fetched = None
    if kept and fetch_top_k > 0:
        try:
            fetched = client.web_fetch([cu for (_, cu, _, _) in kept[:fetch_top_k]],
                                       objective=facet.objective)
        except Exception as e:
            log.warning("web_fetch raised for %s/%s: %s", symbol, facet.name, e)
            fetched = None

    web_dir = Path(web_dir)
    (web_dir / symbol).mkdir(parents=True, exist_ok=True)
    sources: list[dict] = []
    for (r, cu, sid, flagged) in kept:
        text = (fetched or {}).get(cu)
        source_kind = "parallel_mcp_fetch" if text else "parallel_mcp_search"
        if not text:
            text = "\n\n".join(r.excerpts)
        rel = f"{symbol}/{sid}.txt"
        (web_dir / rel).write_text(text or "")
        sources.append({
            "src_id": sid, "symbol": symbol, "url": cu, "title": r.title,
            "published": None if flagged else r.publish_date, "undated": flagged,
            "source_kind": source_kind, "sha256": hashlib.sha256((text or "").encode()).hexdigest(),
            "text_path": rel, "facet": facet.name,
            "excerpt": (r.excerpts[0] if r.excerpts else "")[:1500],
            "host": (urlparse(cu).hostname or ""),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        })
    (web_dir / symbol / f"{facet.name}.json").write_text(json.dumps(sources, indent=1))
    return FacetResult(facet.name, True, sources, getattr(client, "calls_made", 0))


# ---------------- orchestrator (main thread owns the DB) ----------------

def _default_factory(s) -> Callable[[], Optional[McpClient]]:
    limiter = RateLimiter(max(s.rate_limit_s, 1.0))       # >= 1 req/s to the anonymous endpoint

    def make() -> Optional[McpClient]:
        c = McpClient(s.parallel_mcp_url, max_calls=s.parallel_max_calls_per_run, limiter=limiter)
        return c if c.initialize() else None
    return make


def run_webresearch(con, symbol: str, as_of: Optional[date] = None, *,
                    client_factory: Optional[Callable[[], object]] = None,
                    max_workers: int = 3) -> dict:
    """Fan out the three facets in parallel, fan them back in under a guard, and harvest into
    web_sources / news_items / research_runs. Fail-soft: returns a status dict, never raises.
    Only this (main) thread touches DuckDB; each worker owns its own MCP session and file."""
    s = settings()
    symbol = symbol.upper()
    as_of = as_of or date.today()
    web_dir = s.web_dir
    if not s.parallel_enabled:
        return {"status": "DISABLED", "run_id": None, "expected": 0, "received": 0,
                "sources": 0, "calls": 0, "path": str(web_dir / symbol)}

    row = con.execute("SELECT name, industry FROM instruments WHERE symbol = ?", [symbol]).fetchone()
    name, industry = (row[0], row[1]) if row else (None, None)
    facets = facet_specs(symbol, name, industry, as_of)
    factory = client_factory or _default_factory(s)
    run_id = f"webresearch-{symbol}-{as_of}-{uuid.uuid4().hex[:8]}"
    started = datetime.now()

    def work(facet: Facet) -> FacetResult:
        client = factory()
        if client is None:
            return FacetResult(facet.name, False, [], 0)
        return run_facet(client, facet, symbol, as_of, allowed_domains=s.web_allowed_domains,
                         lookback_days=facet.lookback_days, fetch_top_k=s.web_fetch_top_k, web_dir=web_dir)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(facets))) as ex:
        facet_results = list(ex.map(work, facets))

    expected = len(facets)
    received = sum(1 for fr in facet_results if fr.ok)               # fan-in guard: ran, not merely returned
    status = "OK" if received == expected else ("PARTIAL" if received else "FAILED")

    merged: dict[str, dict] = {}
    for fr in facet_results:
        for src in fr.sources:
            merged.setdefault(src["src_id"], src)                   # first facet to surface a url wins
    sources = list(merged.values())
    calls = sum(fr.calls for fr in facet_results)
    visible = date.today()                                          # a web source is usable once fetched

    if sources:
        upsert(con, "web_sources", pd.DataFrame([{
            "src_id": x["src_id"], "symbol": symbol, "run_id": run_id, "url": x["url"], "title": x["title"],
            "published": x["published"], "source_kind": x["source_kind"], "sha256": x["sha256"],
            "text_path": x["text_path"], "fetched_at": x["fetched_at"], "as_of": as_of,
            "visible_from": visible, "facet": x["facet"]} for x in sources]))
        upsert(con, "news_items", pd.DataFrame([{
            "symbol": symbol, "sha1": hashlib.sha1(x["url"].encode()).hexdigest(),
            "published": x["published"], "title": x["title"], "source": x["host"], "url": x["url"],
            "fetched_at": x["fetched_at"], "as_of": as_of, "visible_from": visible} for x in sources]))

    passes = {"expected": expected, "received": received, "sources": len(sources), "calls": calls,
              "facets": {fr.facet: fr.ok for fr in facet_results}}
    upsert(con, "research_runs", pd.DataFrame([{
        "run_id": run_id, "symbol": symbol, "as_of": as_of, "mode": "webresearch", "model": None,
        "status": status, "passes_json": json.dumps(passes), "cost_usd": 0.0,
        "started_at": started, "ended_at": datetime.now()}]))

    return {"status": status, "run_id": run_id, "expected": expected, "received": received,
            "sources": len(sources), "calls": calls, "path": str(web_dir / symbol)}


def web_sources_for_pack(con, symbol: str, as_of: date, limit: int = 12) -> pd.DataFrame:
    """PIT: only sources whose visible_from <= as_of. Dated newest-first, undated last."""
    return con.execute(
        "SELECT src_id, facet, title, url, published, text_path FROM web_sources "
        "WHERE symbol = ? AND visible_from <= ? "
        "ORDER BY (published IS NULL), published DESC LIMIT ?",
        [symbol.upper(), as_of, limit]).df()
