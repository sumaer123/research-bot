"""Tests for T1.4: sweep_xbrl + quality checks.

All tests are fully offline — a FakeHttp tracks call counts so we can assert
zero-cost resume without any network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

_Q2018_BYTES = (FIXTURES / "xbrl_q_2018.xml").read_bytes()
_FY2024_BYTES = (FIXTURES / "xbrl_fy_2024.xml").read_bytes()


# ---------------------------------------------------------------------------
# Fake HTTP client (no network; tracks call counts)
# ---------------------------------------------------------------------------
@dataclass
class _FakeResult:
    status: str
    http_status: Optional[int] = None
    content: Optional[bytes] = None
    error: str = ""
    bytes: int = 0

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "cached")


class FakeHttp:
    """Simulates Http.get_bytes: disk-cache check first (raw_rel), then url_map fallback.

    Mirrors the real Http behaviour:
    - If ``raw_dir / raw_rel`` exists and is non-empty → return "cached" (no calls logged).
    - Otherwise look up url_map; on a successful fetch AND raw_rel given → write the
      archive atomically (tmp.part → rename) so subsequent calls serve from cache.
    """

    def __init__(self, url_map: dict, raw_dir: Optional[Path] = None):
        # url_map: { url -> bytes | "blocked" | "error" | "missing" }
        self.url_map = url_map
        self.raw_dir = raw_dir
        self.calls: list[str] = []

    def get_bytes(self, url: str, *, source: str, key: str,
                  raw_rel: Optional[str] = None) -> _FakeResult:
        # 1. Disk-cache check (mirrors Http.get allow_cached path)
        if raw_rel is not None and self.raw_dir is not None:
            p = self.raw_dir / raw_rel
            if p.exists() and p.stat().st_size > 0:
                content = p.read_bytes()
                return _FakeResult(status="cached", http_status=200,
                                   content=content, bytes=len(content))

        # 2. Network call (tracked)
        self.calls.append(url)
        val = self.url_map.get(url)
        if val is None:
            return _FakeResult(status="missing", http_status=404)
        if val == "blocked":
            return _FakeResult(status="blocked", http_status=403, error="HTTP 403")
        if val == "error":
            return _FakeResult(status="error", error="connection error")
        content = val if isinstance(val, bytes) else val.encode()

        # 3. Atomic write to disk (mirrors Http.get raw_rel path)
        if raw_rel is not None and self.raw_dir is not None:
            p = self.raw_dir / raw_rel
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".part")
            tmp.write_bytes(content)
            tmp.replace(p)

        return _FakeResult(status="ok", http_status=200,
                           content=content, bytes=len(content))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cal_row(symbol, period_end, basis, url, filing_dt=None):
    """Build a row tuple matching sweep_xbrl's expected format."""
    return (symbol, period_end, basis, url, filing_dt or date(2024, 5, 20))


# ---------------------------------------------------------------------------
# Test: fresh sweep loads filings into xbrl_filings + statements_xbrl
# ---------------------------------------------------------------------------
def test_sweep_loads_new_filings(tmp_db):
    from eqr.spine.xbrl import sweep_xbrl

    rows = [
        _cal_row("TESTCO", date(2018, 3, 31), "S",
                 "https://fake/q2018.xml", date(2018, 5, 15)),
        _cal_row("TESTCO", date(2024, 3, 31), "C",
                 "https://fake/fy2024.xml", date(2024, 5, 20)),
    ]
    fake = FakeHttp({
        "https://fake/q2018.xml": _Q2018_BYTES,
        "https://fake/fy2024.xml": _FY2024_BYTES,
    })

    out = sweep_xbrl(tmp_db, fake, rows, run_id="run-1")

    assert out["loaded"] == 2
    assert out["skipped"] == 0
    assert out["errors"] == 0
    assert out["halted"] is False
    assert len(fake.calls) == 2

    # xbrl_filings rows written
    n = tmp_db.execute(
        "SELECT count(*) FROM xbrl_filings WHERE symbol='TESTCO'").fetchone()[0]
    assert n == 2

    # sha256 stamped
    sha_rows = tmp_db.execute(
        "SELECT sha256 FROM xbrl_filings WHERE symbol='TESTCO' AND status='ok'"
    ).fetchall()
    assert all(r[0] is not None and len(r[0]) == 64 for r in sha_rows)

    # statements_xbrl populated
    n_stmts = tmp_db.execute(
        "SELECT count(*) FROM statements_xbrl WHERE symbol='TESTCO'").fetchone()[0]
    assert n_stmts > 0


# ---------------------------------------------------------------------------
# Test: zero-cost resume — second sweep does ZERO fetches
# ---------------------------------------------------------------------------
def test_sweep_zero_cost_resume(tmp_db):
    from eqr.spine.xbrl import sweep_xbrl

    rows = [
        _cal_row("TESTCO", date(2018, 3, 31), "S",
                 "https://fake/q2018.xml", date(2018, 5, 15)),
        _cal_row("TESTCO", date(2024, 3, 31), "C",
                 "https://fake/fy2024.xml", date(2024, 5, 20)),
    ]
    url_map = {
        "https://fake/q2018.xml": _Q2018_BYTES,
        "https://fake/fy2024.xml": _FY2024_BYTES,
    }

    fake1 = FakeHttp(url_map)
    out1 = sweep_xbrl(tmp_db, fake1, rows, run_id="run-1")
    assert out1["loaded"] == 2
    assert len(fake1.calls) == 2

    # Second sweep: same rows, fresh fake client (call counter starts at 0)
    fake2 = FakeHttp(url_map)
    out2 = sweep_xbrl(tmp_db, fake2, rows, run_id="run-2")

    assert len(fake2.calls) == 0, "zero-cost resume: no network calls on second sweep"
    assert out2["loaded"] == 0
    assert out2["skipped"] == 2

    # No duplicate rows in xbrl_filings
    n = tmp_db.execute(
        "SELECT count(*) FROM xbrl_filings WHERE symbol='TESTCO' AND status='ok'"
    ).fetchone()[0]
    assert n == 2


# ---------------------------------------------------------------------------
# Test: stop_after_blocked halts sweep after N consecutive bad fetches
# ---------------------------------------------------------------------------
def test_sweep_stop_after_blocked(tmp_db):
    from eqr.spine.xbrl import sweep_xbrl

    threshold = 3
    urls = [f"https://fake/filing{i}.xml" for i in range(8)]
    rows = [_cal_row(f"SYM{i:02d}", date(2024, 3, 31), "S", urls[i])
            for i in range(8)]

    # All "blocked"
    fake = FakeHttp({url: "blocked" for url in urls})
    out = sweep_xbrl(tmp_db, fake, rows, run_id="run-block",
                     stop_after_blocked=threshold)

    assert out["halted"] is True
    # Exactly `threshold` calls made before halting
    assert len(fake.calls) == threshold


def test_sweep_stop_after_blocked_resets_on_success(tmp_db):
    from eqr.spine.xbrl import sweep_xbrl

    # Pattern: 2 blocked, 1 ok, 2 blocked, 1 ok, 3 blocked → halt at 3rd blocked
    urls = [f"https://fake/f{i}.xml" for i in range(8)]
    rows = [_cal_row(f"SYM{i:02d}", date(2024, 3, 31), "S", urls[i])
            for i in range(8)]

    url_map = {
        urls[0]: "blocked",
        urls[1]: "blocked",
        urls[2]: _Q2018_BYTES,   # success: resets counter
        urls[3]: "blocked",
        urls[4]: "blocked",
        urls[5]: _Q2018_BYTES,   # success: resets counter
        urls[6]: "blocked",
        urls[7]: "blocked",
    }
    # With threshold=3: the run should NOT halt at the first 2 blocked (below threshold)
    # but halts when a fresh run of 3 consecutive blocked is reached.
    # After urls[5] success, urls[6]+[7] = 2 consecutive, still below threshold=3.
    # So: no halt. All 8 urls fetched.
    fake = FakeHttp(url_map)
    out = sweep_xbrl(tmp_db, fake, rows, run_id="run-reset", stop_after_blocked=3)

    assert out["halted"] is False
    assert len(fake.calls) == 8   # all rows processed; counter never reached 3


def test_sweep_stop_after_blocked_halt_mid_run(tmp_db):
    from eqr.spine.xbrl import sweep_xbrl

    # 1 ok, then 3 blocked → halt
    urls = [f"https://fake/g{i}.xml" for i in range(6)]
    rows = [_cal_row(f"SYM{i:02d}", date(2024, 3, 31), "S", urls[i])
            for i in range(6)]
    url_map = {
        urls[0]: _Q2018_BYTES,  # ok
        urls[1]: "blocked",
        urls[2]: "blocked",
        urls[3]: "blocked",     # 3rd consecutive → halt here
        urls[4]: _Q2018_BYTES,  # never reached
        urls[5]: _Q2018_BYTES,
    }
    fake = FakeHttp(url_map)
    out = sweep_xbrl(tmp_db, fake, rows, run_id="run-mid", stop_after_blocked=3)

    assert out["halted"] is True
    # url 0 (ok) + url 1,2,3 (blocked) = 4 calls; 4 and 5 never reached
    assert len(fake.calls) == 4


# ---------------------------------------------------------------------------
# Test: immutable archive is written to raw_dir (if available)
# ---------------------------------------------------------------------------
def test_sweep_writes_immutable_archive(tmp_db, tmp_path):
    from eqr.spine.xbrl import sweep_xbrl

    rows = [_cal_row("TESTCO", date(2018, 3, 31), "S",
                     "https://fake/q2018.xml", date(2018, 5, 15))]
    fake = FakeHttp({"https://fake/q2018.xml": _Q2018_BYTES}, raw_dir=tmp_path)

    sweep_xbrl(tmp_db, fake, rows, run_id="run-arc")

    # Archive is stored under nse/xbrl/TESTCO/<url-basename>
    expected = tmp_path / "nse/xbrl/TESTCO/q2018.xml"
    assert expected.exists(), f"archive not written to {expected}"
    assert expected.read_bytes() == _Q2018_BYTES


# ---------------------------------------------------------------------------
# Test: archive is never overwritten (immutability via Http disk-cache path)
# ---------------------------------------------------------------------------
def test_sweep_archive_not_overwritten(tmp_db, tmp_path):
    from eqr.spine.xbrl import sweep_xbrl

    rows = [_cal_row("TESTCO", date(2018, 3, 31), "S",
                     "https://fake/q2018.xml", date(2018, 5, 15))]
    fake1 = FakeHttp({"https://fake/q2018.xml": _Q2018_BYTES}, raw_dir=tmp_path)
    sweep_xbrl(tmp_db, fake1, rows, run_id="run-1")

    archive = tmp_path / "nse/xbrl/TESTCO/q2018.xml"
    mtime_1 = archive.stat().st_mtime

    # Second sweep: xbrl_filings has sha256 → zero-cost DB skip; archive untouched
    fake2 = FakeHttp({"https://fake/q2018.xml": _Q2018_BYTES}, raw_dir=tmp_path)
    sweep_xbrl(tmp_db, fake2, rows, run_id="run-2")

    assert archive.stat().st_mtime == mtime_1, "archive mtime changed — file was overwritten"


# ---------------------------------------------------------------------------
# Test: disk-cache used after DB wipe (sha256 cleared) — covers I-1 + M-1
# ---------------------------------------------------------------------------
def test_sweep_disk_cache_after_db_wipe(tmp_db, tmp_path):
    """After a successful sweep, if xbrl_filings.sha256 is cleared (DB wipe /
    failed write scenario), a second sweep must serve content from the Http
    disk cache — zero new network calls — and the archive file is unchanged."""
    from eqr.spine.xbrl import sweep_xbrl

    rows = [_cal_row("TESTCO", date(2018, 3, 31), "S",
                     "https://fake/q2018_cache.xml", date(2018, 5, 15))]
    url_map = {"https://fake/q2018_cache.xml": _Q2018_BYTES}

    # First sweep: fetches, archives, loads
    fake1 = FakeHttp(url_map, raw_dir=tmp_path)
    out1 = sweep_xbrl(tmp_db, fake1, rows, run_id="run-1")
    assert out1["loaded"] == 1
    assert len(fake1.calls) == 1

    archive = tmp_path / "nse/xbrl/TESTCO/q2018_cache.xml"
    assert archive.exists(), "archive must be written on first sweep"
    mtime_before = archive.stat().st_mtime
    bytes_before = archive.read_bytes()

    # Simulate DB wipe: clear sha256 so zero-cost resume check won't skip
    tmp_db.execute("UPDATE xbrl_filings SET sha256 = NULL WHERE symbol = 'TESTCO'")

    # Second sweep: empty url_map → network would fail; disk cache must serve
    fake2 = FakeHttp({}, raw_dir=tmp_path)
    out2 = sweep_xbrl(tmp_db, fake2, rows, run_id="run-2")

    assert len(fake2.calls) == 0, "zero network calls — disk cache must be used"
    assert out2["loaded"] == 1            # re-loaded from cache
    assert out2["skipped"] == 0

    # Archive untouched
    assert archive.stat().st_mtime == mtime_before, "archive mtime changed"
    assert archive.read_bytes() == bytes_before, "archive bytes changed"


# ---------------------------------------------------------------------------
# Quality check: xbrl_screener_agreement
# ---------------------------------------------------------------------------
def _insert_xbrl_revenue(con, symbol, period_end, value_cr):
    """Directly insert a single FY revenue row into statements_xbrl (in crore)."""
    from eqr.spine.xbrl import parse_xbrl, load_parsed_xbrl
    # Build a minimal XBRL that will produce exactly `value_cr` crore revenue
    # after scaling.  We say scale = Crores so the raw value == value_cr.
    xml = (
        b'<?xml version="1.0"?>'
        b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
        b' xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2018-03-31/in-bse-fin"'
        b' xmlns:iso4217="http://www.xbrl.org/2003/iso4217">'
        b'<xbrli:context id="FourD"><xbrli:period>'
        b'<xbrli:startDate>' + str(period_end.replace(year=period_end.year - 1)).encode() +
        b'</xbrli:startDate>'
        b'<xbrli:endDate>' + str(period_end).encode() + b'</xbrli:endDate>'
        b'</xbrli:period></xbrli:context>'
        b'<xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>'
        b'<in-bse-fin:LevelOfRoundingUsedInFinancialStatements contextRef="FourD">Crores'
        b'</in-bse-fin:LevelOfRoundingUsedInFinancialStatements>'
        b'<in-bse-fin:RevenueFromOperations contextRef="FourD" unitRef="INR">' +
        str(value_cr).encode() +
        b'</in-bse-fin:RevenueFromOperations>'
        b'</xbrli:xbrl>'
    )
    parsed = parse_xbrl(xml)
    load_parsed_xbrl(con, symbol, parsed, period_end, f"https://fake/{symbol}.xml")


def _insert_screener_revenue(con, symbol, period_end, value_cr):
    """Insert a screener pl_a sales row (in crore)."""
    from datetime import datetime
    con.execute(
        "INSERT INTO statements (symbol, basis, stmt, period_end, line_item, value, "
        "fetched_at, visible_from) VALUES (?, 'consolidated', 'pl_a', ?, 'sales', ?, ?, ?)",
        [symbol, period_end, value_cr, datetime.now(), period_end])


def test_quality_xbrl_screener_agreement_pass(tmp_db):
    from eqr.spine.quality import run_checks

    # 3 symbols: XBRL revenue ≈ screener revenue (within 5%)
    for sym, rev in [("AA", 1000.0), ("BB", 2000.0), ("CC", 3000.0)]:
        _insert_xbrl_revenue(tmp_db, sym, date(2024, 3, 31), rev)
        _insert_screener_revenue(tmp_db, sym, date(2024, 3, 31), rev * 1.03)  # 3% diff

    checks = run_checks(tmp_db, "run-q", date(2024, 12, 31))
    chk = {c["check_name"]: c for c in checks}
    assert "xbrl_screener_agreement" in chk
    assert chk["xbrl_screener_agreement"]["status"] == "PASS", chk["xbrl_screener_agreement"]["detail"]


def test_quality_xbrl_screener_agreement_fail_100x(tmp_db):
    from eqr.spine.quality import run_checks

    # Plant a 100× scale mismatch: XBRL says 15000 cr, screener says 150 cr
    _insert_xbrl_revenue(tmp_db, "MISMATCH", date(2024, 3, 31), 15000.0)
    _insert_screener_revenue(tmp_db, "MISMATCH", date(2024, 3, 31), 150.0)

    checks = run_checks(tmp_db, "run-q", date(2024, 12, 31))
    chk = {c["check_name"]: c for c in checks}
    assert chk["xbrl_screener_agreement"]["status"] == "FAIL", chk["xbrl_screener_agreement"]["detail"]


def test_quality_xbrl_screener_agreement_no_pairs(tmp_db):
    """No pairs → check is skipped (PASS)."""
    from eqr.spine.quality import run_checks

    checks = run_checks(tmp_db, "run-nopairs", date(2024, 12, 31))
    chk = {c["check_name"]: c for c in checks}
    assert chk["xbrl_screener_agreement"]["status"] == "PASS"
    assert "skipped" in chk["xbrl_screener_agreement"]["detail"]


def test_quality_xbrl_screener_agreement_prefers_consolidated(tmp_db):
    """When both consolidated (C) and standalone (S) XBRL FY revenue exist for
    a symbol, the check must pick the consolidated value (basis='C').  If we
    mistakenly pick standalone (which differs by >5%), the check would FAIL.
    With the correct consolidated-first preference the pairs agree and it PASSes.
    """
    from eqr.spine.quality import run_checks
    from eqr.spine.xbrl import parse_xbrl, load_parsed_xbrl

    period_end = date(2024, 3, 31)
    scr_rev = 5000.0   # screener consolidated FY sales

    # Build consolidated XBRL: revenue = 5000 cr (agrees with screener)
    def _make_xbrl(rev, basis_text):
        start = str(period_end.replace(year=period_end.year - 1)).encode()
        end = str(period_end).encode()
        return (
            b'<?xml version="1.0"?>'
            b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            b' xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2018-03-31/in-bse-fin"'
            b' xmlns:iso4217="http://www.xbrl.org/2003/iso4217">'
            b'<xbrli:context id="D"><xbrli:period>'
            b'<xbrli:startDate>' + start + b'</xbrli:startDate>'
            b'<xbrli:endDate>' + end + b'</xbrli:endDate>'
            b'</xbrli:period></xbrli:context>'
            b'<xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>'
            b'<in-bse-fin:LevelOfRoundingUsedInFinancialStatements contextRef="D">Crores'
            b'</in-bse-fin:LevelOfRoundingUsedInFinancialStatements>'
            b'<in-bse-fin:StandaloneConsolidated contextRef="D">' + basis_text + b'</in-bse-fin:StandaloneConsolidated>'
            b'<in-bse-fin:RevenueFromOperations contextRef="D" unitRef="INR">' +
            str(rev).encode() + b'</in-bse-fin:RevenueFromOperations>'
            b'</xbrli:xbrl>'
        )

    # Consolidated filing: rev = 5000 cr (agrees with screener within 5%)
    p_cons = parse_xbrl(_make_xbrl(5000.0, b"Consolidated"))
    load_parsed_xbrl(tmp_db, "DUALCO", p_cons, period_end, "https://fake/DUALCO_C.xml")

    # Standalone filing: rev = 1000 cr (differs by 80% — would cause FAIL if picked)
    p_stand = parse_xbrl(_make_xbrl(1000.0, b"Standalone"))
    load_parsed_xbrl(tmp_db, "DUALCO", p_stand, period_end, "https://fake/DUALCO_S.xml")

    _insert_screener_revenue(tmp_db, "DUALCO", period_end, scr_rev)

    checks = run_checks(tmp_db, "run-dual", date(2024, 12, 31))
    chk = {c["check_name"]: c for c in checks}
    assert chk["xbrl_screener_agreement"]["status"] == "PASS", (
        "consolidated value should be preferred; FAIL means standalone was picked"
    )


# ---------------------------------------------------------------------------
# Quality check: xbrl_freshness
# ---------------------------------------------------------------------------
def test_quality_xbrl_freshness_pass(tmp_db):
    from eqr.spine.quality import run_checks

    # Insert 5 calendar rows + corresponding loaded xbrl_filings rows (>= 80% coverage)
    # Use period_end within 90 days of as_of = 2024-12-31 (i.e. >= 2024-10-02)
    for i in range(5):
        sym = f"FR{i:02d}"
        url = f"https://fake/{sym}.xml"
        period_end = date(2024, 11, 30)  # within 90 days of as_of 2024-12-31
        tmp_db.execute(
            "INSERT INTO results_calendar (symbol, period_end, consolidated, xbrl_url, filing_dt) "
            "VALUES (?, ?, 'S', ?, ?)",
            [sym, period_end, url, datetime.now()])
        tmp_db.execute(
            "INSERT OR REPLACE INTO xbrl_filings "
            "(symbol, period_end, basis, xbrl_url, status, fetched_at) "
            "VALUES (?, ?, 'S', ?, 'ok', ?)",
            [sym, period_end, url, datetime.now()])

    checks = run_checks(tmp_db, "run-fresh", date(2024, 12, 31))
    chk = {c["check_name"]: c for c in checks}
    assert chk["xbrl_freshness"]["status"] == "PASS", chk["xbrl_freshness"]["detail"]
    assert "5/5" in chk["xbrl_freshness"]["detail"]


def test_quality_xbrl_freshness_fail(tmp_db):
    from eqr.spine.quality import run_checks

    # 5 calendar rows, only 1 loaded (20% coverage < 80%)
    # period_end within 90 days of as_of = 2024-12-31
    for i in range(5):
        sym = f"LW{i:02d}"
        url = f"https://fake/{sym}.xml"
        period_end = date(2024, 11, 30)
        tmp_db.execute(
            "INSERT INTO results_calendar (symbol, period_end, consolidated, xbrl_url, filing_dt) "
            "VALUES (?, ?, 'S', ?, ?)",
            [sym, period_end, url, datetime.now()])
        if i == 0:  # only first row loaded
            tmp_db.execute(
                "INSERT OR REPLACE INTO xbrl_filings "
                "(symbol, period_end, basis, xbrl_url, status, fetched_at) "
                "VALUES (?, ?, 'S', ?, 'ok', ?)",
                [sym, period_end, url, datetime.now()])

    checks = run_checks(tmp_db, "run-stale", date(2024, 12, 31))
    chk = {c["check_name"]: c for c in checks}
    assert chk["xbrl_freshness"]["status"] == "FAIL", chk["xbrl_freshness"]["detail"]
    assert "1/5" in chk["xbrl_freshness"]["detail"]


def test_quality_xbrl_freshness_no_calendar_entries(tmp_db):
    """No calendar rows → skipped (PASS)."""
    from eqr.spine.quality import run_checks

    checks = run_checks(tmp_db, "run-empty", date(2024, 12, 31))
    chk = {c["check_name"]: c for c in checks}
    assert chk["xbrl_freshness"]["status"] == "PASS"
    assert "skipped" in chk["xbrl_freshness"]["detail"]
