"""T3/T4/T5/T11: facet specs, pure filters, the parallel worker, the orchestrator + storage,
and the doctrine guard. No network anywhere — the worker is driven by a fake McpClient."""
import ast
from datetime import date
from pathlib import Path

import pytest

from eqr.research import webresearch as wr
from eqr.research.parallel_client import SearchResult

ROOT = Path(__file__).resolve().parent.parent


# ---------------- T3: facet specs + pure filters ----------------

def test_facet_specs_are_independent_and_well_shaped():
    facets = wr.facet_specs("KIRLOSENG", "Kirloskar Oil Engines", "Diesel Engines", date(2026, 9, 16))
    assert [f.name for f in facets] == ["results", "actions", "sector"]
    for f in facets:
        assert f.objective and isinstance(f.objective, str)
        assert 2 <= len(f.queries) <= 3
        for q in f.queries:
            n = len(q.split())
            assert 3 <= n <= 6, (f.name, q, n)
        assert f.lookback_days > 0
    # fake-edge: no facet's spec is derived from another facet's output
    assert len({f.name for f in facets}) == 3


def test_allowed_host_suffix_match_and_allow_all():
    allowed = ("nseindia.com", "moneycontrol.com")
    assert wr.allowed_host("https://www.moneycontrol.com/news/x", allowed)
    assert wr.allowed_host("https://nsearchives.nseindia.com/abc.pdf", allowed)
    assert not wr.allowed_host("https://tracxn.com/company/x", allowed)
    assert not wr.allowed_host("https://evilmoneycontrol.com/x", allowed)   # not a real suffix
    assert wr.allowed_host("https://anything.example/x", ())               # empty = allow all


def test_within_lookback_keeps_undated_but_flags_it():
    as_of = date(2026, 9, 16)
    keep, flagged = wr.within_lookback(None, as_of, 180)
    assert keep and flagged
    keep, flagged = wr.within_lookback("2026-08-01", as_of, 180)
    assert keep and not flagged
    keep, flagged = wr.within_lookback("2020-01-01", as_of, 180)
    assert not keep
    keep, flagged = wr.within_lookback("2027-01-01", as_of, 180)            # after as_of -> out
    assert not keep
    keep, flagged = wr.within_lookback("garbage", as_of, 180)               # unparseable -> undated
    assert keep and flagged


def test_canonical_url_strips_utm_and_fragment_and_src_id_is_stable():
    a = wr.canonical_url("https://x.com/a?utm_source=parallel&id=7#frag")
    b = wr.canonical_url("https://x.com/a?id=7")
    assert a == b == "https://x.com/a?id=7"
    s1 = wr.src_id_for("KIRLOSENG", "https://x.com/a?utm_source=parallel&id=7#frag")
    s2 = wr.src_id_for("KIRLOSENG", "https://x.com/a?id=7")
    assert s1 == s2 and s1.startswith("KIRLOSENG-w") and len(s1) == len("KIRLOSENG-w") + 10


# ---------------- T4: the worker ----------------

class FakeClient:
    """A canned McpClient: one search payload, fetch echoes short text per url."""
    def __init__(self, results, fetch_text="FETCHED BODY", search_none=False, fetch_none=False):
        self._results = results
        self._fetch_text = fetch_text
        self._search_none = search_none
        self._fetch_none = fetch_none
        self.calls_made = 0
        self.searched = []
        self.fetched = []

    def web_search(self, objective, queries):
        self.calls_made += 1
        self.searched.append((objective, tuple(queries)))
        return None if self._search_none else list(self._results)

    def web_fetch(self, urls, objective=None, full_content=False):
        self.calls_made += 1
        self.fetched.append(tuple(urls))
        if self._fetch_none:
            return None
        return {u: f"{self._fetch_text} {u}" for u in urls}


def _results(as_of):
    from datetime import timedelta
    fresh = (as_of - timedelta(days=40)).isoformat()     # within every facet's lookback
    old = (as_of - timedelta(days=900)).isoformat()      # beyond every lookback
    return [
        SearchResult("https://www.moneycontrol.com/news/kirlos-q1?utm_source=parallel", "Q1 FY27",
                     fresh, ["Kirloskar Oil Engines registers 16% YoY revenue growth in Q1 FY27."]),
        SearchResult("https://www.business-standard.com/kirlos-guidance", "Guidance",
                     None, ["Management guided to double-digit growth."]),   # undated -> kept, flagged
        SearchResult("https://tracxn.com/company/kirlos", "Profile",
                     fresh, ["aggregator profile"]),                         # off-domain -> dropped
        SearchResult("https://www.livemint.com/kirlos-old", "Old",
                     old, ["stale"]),                                        # too old -> dropped
        SearchResult("https://www.moneycontrol.com/news/kirlos-q1?utm_medium=ai", "dup",
                     fresh, ["duplicate of the first by canonical url"]),    # dup -> deduped
    ]


def test_run_facet_filters_dedupes_fetches_and_writes(tmp_path):
    as_of = date(2026, 9, 16)
    facet = wr.facet_specs("KIRLOSENG", "Kirloskar Oil Engines", "Diesel Engines", as_of)[0]
    client = FakeClient(_results(as_of))
    fr = wr.run_facet(client, facet, "KIRLOSENG", as_of,
                      allowed_domains=("nseindia.com", "moneycontrol.com", "business-standard.com", "livemint.com"),
                      lookback_days=180, fetch_top_k=3, web_dir=tmp_path)
    assert fr.ok
    # moneycontrol (deduped to one) + business-standard = 2 kept; tracxn + old + dup dropped
    urls = {s["url"] for s in fr.sources}
    assert urls == {"https://www.moneycontrol.com/news/kirlos-q1",         # canonicalised, utm stripped
                    "https://www.business-standard.com/kirlos-guidance"}
    assert (tmp_path / "KIRLOSENG" / f"{facet.name}.json").exists()
    # the undated business-standard source is flagged
    bs = next(s for s in fr.sources if "business-standard" in s["url"])
    assert bs["undated"] is True
    # text files written for fetched sources
    for s in fr.sources:
        assert (tmp_path / s["text_path"]).exists() or Path(s["text_path"]).exists()


def test_run_facet_not_ok_when_search_returns_none(tmp_path):
    as_of = date(2026, 9, 16)
    facet = wr.facet_specs("KIRLOSENG", "Kirloskar Oil Engines", "Diesel Engines", as_of)[0]
    client = FakeClient([], search_none=True)
    fr = wr.run_facet(client, facet, "KIRLOSENG", as_of, allowed_domains=(), lookback_days=180,
                      fetch_top_k=3, web_dir=tmp_path)
    assert not fr.ok and fr.sources == []


def test_run_facet_never_touches_db_object():
    # the worker signature accepts no connection; enforce that by construction
    import inspect
    params = set(inspect.signature(wr.run_facet).parameters)
    assert "con" not in params and "connection" not in params


# ---------------- T5: orchestrator + storage ----------------

import threading


class ConGuard:
    """Delegates to a real connection but raises if a mutating call comes from a worker thread."""
    def __init__(self, con):
        self._con = con
        self._main = threading.main_thread()

    def __getattr__(self, k):
        attr = getattr(self._con, k)
        if k in ("execute", "executemany", "register", "unregister") and callable(attr):
            def guarded(*a, **kw):
                assert threading.current_thread() is self._main, f"{k} off main thread"
                return attr(*a, **kw)
            return guarded
        return attr


def _factory(results, **kw):
    threads = []

    def make():
        c = FakeClient(list(results), **kw)
        orig = c.web_search

        def rec(objective, queries):
            threads.append(threading.current_thread())
            return orig(objective, queries)
        c.web_search = rec
        return c
    make.threads = threads
    return make


def _seed_instruments(tmp_db):
    # instruments give run_webresearch a name/industry; as_of = today so visible_from(=fetch date=today)
    # is PIT-visible, matching real standalone `eqr webresearch` (as_of defaults to today).
    from tests.conftest import make_synthetic_market
    make_synthetic_market(tmp_db, n_symbols=6, n_days=320)               # >300: conftest plants a day-300 event
    return date.today()


def test_orchestrator_stores_sources_runs_and_news(tmp_db, monkeypatch):
    monkeypatch.setenv("EQR_PARALLEL_ENABLED", "1")
    as_of = _seed_instruments(tmp_db)
    fac = _factory(_results(as_of))
    out = wr.run_webresearch(ConGuard(tmp_db), "S05", as_of, client_factory=fac)
    assert out["status"] == "OK" and out["expected"] == 3 and out["received"] == 3
    assert out["sources"] >= 2
    ws = tmp_db.execute("SELECT count(*), count(facet) FROM web_sources WHERE symbol='S05'").fetchone()
    assert ws[0] == out["sources"] and ws[1] == out["sources"]      # facet populated on every row
    facets = {r[0] for r in tmp_db.execute("SELECT DISTINCT facet FROM web_sources WHERE symbol='S05'").fetchall()}
    assert facets and facets <= {"results", "actions", "sector"}
    ni = tmp_db.execute("SELECT count(*) FROM news_items WHERE symbol='S05'").fetchone()[0]
    assert ni == out["sources"]
    rr = tmp_db.execute("SELECT mode, status, cost_usd, passes_json FROM research_runs WHERE run_id=?",
                        [out["run_id"]]).fetchone()
    assert rr[0] == "webresearch" and rr[1] == "OK" and rr[2] == 0.0
    import json as _j
    assert _j.loads(rr[3])["received"] == 3
    # workers ran off the main thread; the DB was only ever touched from main (ConGuard didn't raise)
    assert fac.threads and all(t is not threading.main_thread() for t in fac.threads)


def test_partial_when_a_worker_fails(tmp_db, monkeypatch):
    monkeypatch.setenv("EQR_PARALLEL_ENABLED", "1")
    as_of = _seed_instruments(tmp_db)
    n = [0]
    lock = threading.Lock()

    def make():
        with lock:
            n[0] += 1
            fail = n[0] == 2                 # exactly one worker's search returns None
        return FakeClient(_results(as_of), search_none=fail)
    out = wr.run_webresearch(tmp_db, "S05", as_of, client_factory=make)
    assert out["status"] == "PARTIAL" and out["received"] == 2 and out["expected"] == 3
    assert _json_loads(tmp_db, out["run_id"])["received"] == 2


def _json_loads(con, run_id):
    import json as _j
    return _j.loads(con.execute("SELECT passes_json FROM research_runs WHERE run_id=?", [run_id]).fetchone()[0])


def test_disabled_writes_nothing(tmp_db, monkeypatch):
    as_of = _seed_instruments(tmp_db)
    monkeypatch.setenv("EQR_PARALLEL_ENABLED", "0")
    out = wr.run_webresearch(tmp_db, "S05", as_of, client_factory=_factory(_results(as_of)))
    assert out["status"] == "DISABLED" and out["run_id"] is None
    assert tmp_db.execute("SELECT count(*) FROM web_sources").fetchone()[0] == 0
    assert tmp_db.execute("SELECT count(*) FROM research_runs").fetchone()[0] == 0


def test_idempotent_rerun_does_not_duplicate_sources(tmp_db, monkeypatch):
    monkeypatch.setenv("EQR_PARALLEL_ENABLED", "1")
    as_of = _seed_instruments(tmp_db)
    wr.run_webresearch(tmp_db, "S05", as_of, client_factory=_factory(_results(as_of)))
    n1 = tmp_db.execute("SELECT count(*) FROM web_sources WHERE symbol='S05'").fetchone()[0]
    wr.run_webresearch(tmp_db, "S05", as_of, client_factory=_factory(_results(as_of)))
    n2 = tmp_db.execute("SELECT count(*) FROM web_sources WHERE symbol='S05'").fetchone()[0]
    assert n1 == n2 and n1 >= 2
    assert tmp_db.execute("SELECT count(*) FROM research_runs").fetchone()[0] == 2   # two runs logged


def test_web_sources_for_pack_is_point_in_time(tmp_db, monkeypatch):
    monkeypatch.setenv("EQR_PARALLEL_ENABLED", "1")
    as_of = _seed_instruments(tmp_db)
    wr.run_webresearch(tmp_db, "S05", as_of, client_factory=_factory(_results(as_of)))
    # a source made visible only tomorrow must not appear for today's pack
    tmp_db.execute("UPDATE web_sources SET visible_from = ? WHERE symbol='S05' "
                   "AND src_id = (SELECT min(src_id) FROM web_sources WHERE symbol='S05')",
                   [as_of + __import__('datetime').timedelta(days=1)])
    df = wr.web_sources_for_pack(tmp_db, "S05", as_of)
    assert len(df) >= 1
    assert all(str(v) <= str(as_of) for v in df["published"].dropna())  # sanity; PIT on visible_from
    hidden = tmp_db.execute("SELECT count(*) FROM web_sources WHERE symbol='S05' AND visible_from > ?",
                            [as_of]).fetchone()[0]
    assert hidden == 1 and len(df) == tmp_db.execute(
        "SELECT count(*) FROM web_sources WHERE symbol='S05' AND visible_from <= ?", [as_of]).fetchone()[0]


# ---------------- T11: doctrine guard ----------------

def test_number_producing_modules_do_not_import_web_research():
    banned = ("parallel_client", "webresearch", "verify")
    for pkg in ("rating", "features", "strategy", "validate"):
        for py in (ROOT / "eqr" / pkg).rglob("*.py"):
            src = py.read_text()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not any(b in node.module for b in banned), f"{py} imports {node.module}"
            for b in banned:
                assert f"import {b}" not in src, f"{py} mentions import {b}"
            # no number path may read the web tables
            assert "web_sources" not in src and "news_items" not in src, py
