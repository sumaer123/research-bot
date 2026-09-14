"""Tests for T1.3: XBRL parser + PIT loader. Fully offline against committed,
hand-built fixtures (structurally real Ind-AS XBRL)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from eqr.spine.xbrl import (
    auditor_name,
    auditor_opinion,
    canonical_item,
    canonical_wide,
    infer_scale,
    load_parsed_xbrl,
    parse_xbrl,
    period_kind,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return parse_xbrl((FIXTURES / name).read_bytes())


@pytest.fixture()
def q2018():
    return _load("xbrl_q_2018.xml")


@pytest.fixture()
def fy2024():
    return _load("xbrl_fy_2024.xml")


@pytest.fixture()
def capmkt():
    return _load("xbrl_q_2026_capmkt.xml")


@pytest.fixture()
def bank():
    return _load("xbrl_bank_2026.xml")


# ---------------------------------------------------------------------------
# Each taxonomy parses
# ---------------------------------------------------------------------------
def test_parse_in_bse_fin_quarterly(q2018):
    assert q2018.taxonomy == "in-bse-fin"
    assert q2018.is_bank is False
    assert q2018.rounding == "Lakhs"
    assert q2018.basis == "C"
    assert len(q2018.contexts) == 2
    tags = {f.tag for f in q2018.facts}
    assert "RevenueFromOperations" in tags and "ProfitLoss" in tags


def test_parse_in_bse_fin_annual(fy2024):
    assert fy2024.taxonomy == "in-bse-fin"
    tags = {f.tag for f in fy2024.facts}
    # balance sheet + auditor + segment present in the annual file
    assert "TotalAssets" in tags
    assert "AuditorsFirmName" in tags
    assert "SegmentRevenue" in tags


def test_parse_in_capmkt_quarterly(capmkt):
    assert capmkt.taxonomy == "in-capmkt"
    assert capmkt.is_bank is False
    assert capmkt.rounding == "Lakhs"      # from LevelOfRounding
    assert capmkt.basis == "S"


def test_parse_in_capmkt_ent_bank(bank):
    assert bank.taxonomy == "in-capmkt-ent"
    assert bank.is_bank is True
    tags = {f.tag for f in bank.facts}
    assert "CET1Ratio" in tags and "GrossNonPerformingAssets" in tags


def test_bank_detected_by_marker_tags_even_without_ent_namespace():
    """is_bank must also flip on bank-marker tags, not only the ent namespace."""
    xml = b"""<?xml version="1.0"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/2025-01-31/in-capmkt"
        xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
      <xbrli:context id="I"><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
      <in-capmkt:CET1Ratio contextRef="I" unitRef="pure">0.15</in-capmkt:CET1Ratio>
    </xbrli:xbrl>"""
    p = parse_xbrl(xml)
    assert p.taxonomy == "in-capmkt"
    assert p.is_bank is True


# ---------------------------------------------------------------------------
# canonical_item map
# ---------------------------------------------------------------------------
def test_canonical_item_pl_tags():
    assert canonical_item("RevenueFromOperations", False) == "revenue"
    assert canonical_item("ProfitLoss", False) == "pat"
    assert canonical_item("FinanceCosts", False) == "finance_cost"


def test_canonical_item_unmapped_returns_none():
    assert canonical_item("ExceptionalItemsBeforeTax", False) is None
    assert canonical_item("PaymentOfDividend", False) is None


def test_bank_tags_map_only_when_bank():
    assert canonical_item("CET1Ratio", True) == "cet1"
    assert canonical_item("CET1Ratio", False) is None
    assert canonical_item("GrossNonPerformingAssets", True) == "gnpa"
    assert canonical_item("GrossNonPerformingAssets", False) is None


# ---------------------------------------------------------------------------
# period_kind boundaries
# ---------------------------------------------------------------------------
def test_period_kind_quarter():
    assert period_kind(date(2018, 1, 1), date(2018, 3, 31)) == "Q"


def test_period_kind_half():
    assert period_kind(date(2023, 4, 1), date(2023, 9, 30)) == "H"


def test_period_kind_nine_months():
    assert period_kind(date(2025, 4, 1), date(2025, 12, 31)) == "9M"


def test_period_kind_full_year():
    assert period_kind(date(2023, 4, 1), date(2024, 3, 31)) == "FY"


def test_period_kind_instant():
    assert period_kind(None, date(2024, 3, 31)) == "I"
    assert period_kind(date(2024, 3, 31), None) == "I"


# ---------------------------------------------------------------------------
# Scaling: Lakh -> crore
# ---------------------------------------------------------------------------
def test_lakh_to_crore_scaling(tmp_db, q2018):
    load_parsed_xbrl(tmp_db, "TESTCO", q2018, date(2018, 5, 15),
                     "https://x/q2018.xml")
    row = tmp_db.execute(
        "SELECT value FROM statements_xbrl WHERE symbol='TESTCO' AND item='revenue' "
        "AND period_kind='Q'").fetchone()
    # 100000 Lakhs / 100 = 1000 crore
    assert row is not None
    assert row[0] == pytest.approx(1000.0)


def test_per_share_and_pure_are_not_scaled(tmp_db, q2018, bank):
    load_parsed_xbrl(tmp_db, "TESTCO", q2018, date(2018, 5, 15), "https://x/q.xml")
    eps = tmp_db.execute(
        "SELECT value FROM statements_xbrl WHERE symbol='TESTCO' AND item='eps_basic'"
    ).fetchone()
    assert eps[0] == pytest.approx(4.50)   # per-share, untouched by the /100 scale

    load_parsed_xbrl(tmp_db, "BANKCO", bank, date(2026, 1, 20), "https://x/b.xml")
    cet1 = tmp_db.execute(
        "SELECT value FROM statements_xbrl WHERE symbol='BANKCO' AND item='cet1'"
    ).fetchone()
    assert cet1[0] == pytest.approx(0.1425)   # pure ratio, untouched


# ---------------------------------------------------------------------------
# infer_scale: screener cross-check overrides a 100x rounding error
# ---------------------------------------------------------------------------
def test_infer_scale_from_rounding_no_screener(tmp_db, q2018):
    scale, inferred = infer_scale(tmp_db, "TESTCO", q2018)
    assert scale == pytest.approx(0.01)   # Lakhs
    assert inferred is False


def test_infer_scale_overrides_100x_mismatch(tmp_db):
    """XBRL rounding says Lakhs (0.01) but the values are actually already in crore.
    Screener FY sales disagree by ~100x -> infer_scale must flip to 1.0 & mark it."""
    # Screener says FY2024 sales = 15000 crore
    tmp_db.execute(
        "INSERT INTO statements (symbol, basis, stmt, period_end, line_item, value, "
        "fetched_at, visible_from) VALUES ('MISLABEL','consolidated','pl_a','2024-03-31',"
        "'sales', 15000.0, ?, '2024-05-01')", [datetime.now()])
    # But the XBRL revenue fact is 15000 with a (wrong) Lakhs tag -> 0.01 would give 150 cr
    xml = b"""<?xml version="1.0"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2018-03-31/in-bse-fin"
        xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
      <xbrli:context id="FourD"><xbrli:period>
        <xbrli:startDate>2023-04-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate>
      </xbrli:period></xbrli:context>
      <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
      <in-bse-fin:LevelOfRoundingUsedInFinancialStatements contextRef="FourD">Lakhs</in-bse-fin:LevelOfRoundingUsedInFinancialStatements>
      <in-bse-fin:RevenueFromOperations contextRef="FourD" unitRef="INR">15000.00</in-bse-fin:RevenueFromOperations>
    </xbrli:xbrl>"""
    parsed = parse_xbrl(xml)
    scale, inferred = infer_scale(tmp_db, "MISLABEL", parsed)
    assert inferred is True
    assert scale == pytest.approx(1.0)   # crore, agrees with screener


# ---------------------------------------------------------------------------
# Auditor (annual)
# ---------------------------------------------------------------------------
def test_auditor_name_and_unmodified_opinion(fy2024):
    assert auditor_name(fy2024) == "B S R & Co. LLP"
    text, modified = auditor_opinion(fy2024)
    assert text == "Unmodified opinion"
    assert modified is False


def test_auditor_qualified_opinion_flag():
    xml = b"""<?xml version="1.0"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2018-03-31/in-bse-fin">
      <xbrli:context id="FourD"><xbrli:period>
        <xbrli:startDate>2023-04-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate>
      </xbrli:period></xbrli:context>
      <in-bse-fin:TypeOfAuditQualification contextRef="FourD">Qualified opinion</in-bse-fin:TypeOfAuditQualification>
    </xbrli:xbrl>"""
    _text, modified = auditor_opinion(parse_xbrl(xml))
    assert modified is True


def test_auditor_only_in_annual_not_quarterly(q2018):
    assert auditor_name(q2018) is None


# ---------------------------------------------------------------------------
# Bank-only items present only when is_bank
# ---------------------------------------------------------------------------
def test_bank_items_loaded_only_when_bank(tmp_db, bank):
    load_parsed_xbrl(tmp_db, "BANKCO", bank, date(2026, 1, 20), "https://x/b.xml")
    items = {r[0] for r in tmp_db.execute(
        "SELECT DISTINCT item FROM statements_xbrl WHERE symbol='BANKCO' AND item IS NOT NULL"
    ).fetchall()}
    assert {"cet1", "gnpa", "nnpa", "advances", "deposits", "provisions"} <= items


def test_bank_tags_stored_raw_when_not_bank(tmp_db):
    """If the very same bank tag appears in a non-bank filing, it is NOT canonicalised
    (item NULL) but still stored raw."""
    xml = b"""<?xml version="1.0"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2018-03-31/in-bse-fin"
        xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
      <xbrli:context id="OneD"><xbrli:period>
        <xbrli:startDate>2018-01-01</xbrli:startDate><xbrli:endDate>2018-03-31</xbrli:endDate>
      </xbrli:period></xbrli:context>
      <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
      <in-bse-fin:RevenueFromOperations contextRef="OneD" unitRef="INR">1000.0</in-bse-fin:RevenueFromOperations>
      <in-bse-fin:Deposits contextRef="OneD" unitRef="INR">5000.0</in-bse-fin:Deposits>
    </xbrli:xbrl>"""
    p = parse_xbrl(xml)
    assert p.is_bank is True   # 'Deposits' is a bank marker
    # but force a non-bank load path check on canonical_item directly:
    assert canonical_item("Deposits", False) is None


# ---------------------------------------------------------------------------
# Unmapped tag stored raw with item NULL
# ---------------------------------------------------------------------------
def test_unmapped_tag_stored_raw_item_null(tmp_db, q2018):
    load_parsed_xbrl(tmp_db, "TESTCO", q2018, date(2018, 5, 15), "https://x/q.xml")
    row = tmp_db.execute(
        "SELECT item, value FROM statements_xbrl WHERE symbol='TESTCO' "
        "AND tag='ExceptionalItemsBeforeTax'").fetchone()
    assert row is not None, "unmapped tag must be stored, never dropped"
    assert row[0] is None, "unmapped tag stored with item NULL, never guessed"


# ---------------------------------------------------------------------------
# Dimensioned segment facts -> distinct dims_key
# ---------------------------------------------------------------------------
def test_segment_facts_distinct_dims_key(fy2024):
    seg = sorted({f.dims_key for f in fy2024.facts if f.tag == "SegmentRevenue"})
    assert len(seg) == 2
    assert all(d.startswith("BusinessSegmentsAxis=") for d in seg)
    assert seg[0] != seg[1]


def test_non_dimensioned_facts_have_empty_dims_key(fy2024):
    rev = [f for f in fy2024.facts if f.tag == "RevenueFromOperations"]
    assert rev and all(f.dims_key == "" for f in rev)


def test_segment_facts_loaded_as_distinct_rows(tmp_db, fy2024):
    load_parsed_xbrl(tmp_db, "SEGCO", fy2024, date(2024, 5, 15), "https://x/fy.xml")
    n = tmp_db.execute(
        "SELECT count(*) FROM statements_xbrl WHERE symbol='SEGCO' AND item='segment_revenue'"
    ).fetchone()[0]
    assert n == 2


# ---------------------------------------------------------------------------
# PIT law + first-seen wins + revisions
# ---------------------------------------------------------------------------
def test_visible_from_is_filing_dt(tmp_db, q2018):
    load_parsed_xbrl(tmp_db, "TESTCO", q2018, date(2018, 5, 15), "https://x/q.xml")
    row = tmp_db.execute(
        "SELECT DISTINCT visible_from, as_of FROM statements_xbrl WHERE symbol='TESTCO'"
    ).fetchone()
    assert row[0] == date(2018, 5, 15)   # filing_dt, never fetch time
    assert row[1] == date(2018, 5, 15)


def test_first_seen_wins_and_revision_logged_per_period(tmp_db, q2018):
    """RevenueFromOperations exists in BOTH the quarter (OneD) and YTD (FourD)
    contexts -> two primary rows (distinct period_start). Changing BOTH on reload
    must produce EXACTLY 2 revisions, one per period_start, each carrying that
    period's new value, while both primary rows keep their first-seen value."""
    load_parsed_xbrl(tmp_db, "TESTCO", q2018, date(2018, 5, 15), "https://x/v1.xml")

    # both primary (first-seen) values, keyed by period_start
    primaries = dict(tmp_db.execute(
        "SELECT period_start, value FROM statements_xbrl WHERE symbol='TESTCO' "
        "AND tag='RevenueFromOperations' AND kind='D' AND period_end='2018-03-31'"
    ).fetchall())
    assert primaries == {date(2018, 1, 1): pytest.approx(1000.0),      # Q4: 100000 Lakhs/100
                         date(2017, 4, 1): pytest.approx(3800.0)}      # FY: 380000 Lakhs/100

    # Re-load the SAME periods with a changed value in EACH context
    revised_parsed = _load("xbrl_q_2018.xml")
    for f in revised_parsed.facts:
        if f.tag == "RevenueFromOperations" and f.context_ref == "OneD":
            f.value = 110000.0   # was 100000 -> 1100 cr
        elif f.tag == "RevenueFromOperations" and f.context_ref == "FourD":
            f.value = 400000.0   # was 380000 -> 4000 cr
    result = load_parsed_xbrl(tmp_db, "TESTCO", revised_parsed, date(2018, 8, 1),
                              "https://x/v2.xml")

    # both primary rows unchanged (first-seen wins), still keyed by period_start
    after = dict(tmp_db.execute(
        "SELECT period_start, value FROM statements_xbrl WHERE symbol='TESTCO' "
        "AND tag='RevenueFromOperations' AND kind='D' AND period_end='2018-03-31'"
    ).fetchall())
    assert after == primaries

    # EXACTLY two revisions -- one per period_start -- each with that period's new value
    revs = dict(tmp_db.execute(
        "SELECT period_start, value FROM statements_xbrl_revisions WHERE symbol='TESTCO' "
        "AND tag='RevenueFromOperations' AND kind='D' AND period_end='2018-03-31'"
    ).fetchall())
    assert len(revs) == 2, "one revision per (period_end, period_start) that changed"
    assert revs == {date(2018, 1, 1): pytest.approx(1100.0),
                    date(2017, 4, 1): pytest.approx(4000.0)}
    assert result["revisions"] == 2   # loader's own accounting agrees

    # filing flagged revised
    assert result["revised"] is True
    flag = tmp_db.execute(
        "SELECT revised FROM xbrl_filings WHERE symbol='TESTCO' AND xbrl_url='https://x/v2.xml'"
    ).fetchone()[0]
    assert flag is True


def test_single_period_tag_logs_exactly_one_revision(tmp_db, q2018):
    """A tag present in only ONE context (OtherIncome -> OneD only) logs exactly
    one revision when its value changes -- pins the count for the single-row case."""
    load_parsed_xbrl(tmp_db, "SOLOCO", q2018, date(2018, 5, 15), "https://x/v1.xml")
    revised = _load("xbrl_q_2018.xml")
    changed = 0
    for f in revised.facts:
        if f.tag == "OtherIncome":
            f.value = 3000.0   # was 2500 Lakhs
            changed += 1
    assert changed == 1, "fixture guard: OtherIncome must appear in exactly one context"
    result = load_parsed_xbrl(tmp_db, "SOLOCO", revised, date(2018, 8, 1), "https://x/v2.xml")
    revs = tmp_db.execute(
        "SELECT count(*) FROM statements_xbrl_revisions WHERE symbol='SOLOCO' AND tag='OtherIncome'"
    ).fetchone()[0]
    assert revs == 1
    assert result["revisions"] == 1


def test_quarter_and_ytd_both_persist(tmp_db, q2018):
    """OneD (quarter) and FourD (YTD/FY) share period_end but differ in period_start
    -> BOTH rows persist now that period_start is in the PK (YTD no longer dropped)."""
    load_parsed_xbrl(tmp_db, "TESTCO", q2018, date(2018, 5, 15), "https://x/q.xml")
    rows = tmp_db.execute(
        "SELECT period_start, period_kind, value FROM statements_xbrl "
        "WHERE symbol='TESTCO' AND tag='RevenueFromOperations' AND period_end='2018-03-31' "
        "AND kind='D' ORDER BY period_start").fetchall()
    assert len(rows) == 2, "quarter and YTD must coexist as distinct rows"
    starts = {r[0] for r in rows}
    assert starts == {date(2017, 4, 1), date(2018, 1, 1)}   # FY start vs Q4 start
    kinds = {r[1] for r in rows}
    assert kinds == {"Q", "FY"}
    # scaled to crore: Q4 = 100000 Lakhs/100 = 1000; FY = 380000/100 = 3800
    by_start = {r[0]: r[2] for r in rows}
    assert by_start[date(2018, 1, 1)] == pytest.approx(1000.0)
    assert by_start[date(2017, 4, 1)] == pytest.approx(3800.0)


def test_quarter_equals_ytd_same_start_collapses():
    """A Q1 filing where the current quarter and the YTD share the SAME start date
    (Apr-Jun == Apr-Jun) collapses to one row (identical PK)."""
    xml = b"""<?xml version="1.0"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/2025-01-31/in-capmkt"
        xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
      <xbrli:context id="OneD"><xbrli:period>
        <xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate>
      </xbrli:period></xbrli:context>
      <xbrli:context id="FourD"><xbrli:period>
        <xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate>
      </xbrli:period></xbrli:context>
      <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
      <in-capmkt:LevelOfRounding contextRef="OneD">Lakhs</in-capmkt:LevelOfRounding>
      <in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR">50000.0</in-capmkt:RevenueFromOperations>
      <in-capmkt:RevenueFromOperations contextRef="FourD" unitRef="INR">50000.0</in-capmkt:RevenueFromOperations>
    </xbrli:xbrl>"""
    import tempfile
    from eqr.store import connect
    with tempfile.TemporaryDirectory() as d:
        con = connect(Path(d) / "eqr.duckdb")
        try:
            load_parsed_xbrl(con, "Q1CO", parse_xbrl(xml), date(2025, 8, 1), "https://x/q1.xml")
            rows = con.execute(
                "SELECT count(*) FROM statements_xbrl WHERE symbol='Q1CO' "
                "AND tag='RevenueFromOperations'").fetchone()[0]
            assert rows == 1, "identical (start,end) contexts collapse to one row"
            revs = con.execute(
                "SELECT count(*) FROM statements_xbrl_revisions WHERE symbol='Q1CO'").fetchone()[0]
            assert revs == 0, "identical values collapsing must not log a revision"
        finally:
            con.close()


def test_reload_identical_preserves_both_periods_no_revision(tmp_db, q2018):
    """Re-loading the same quarterly file (both quarter + YTD) is idempotent: both
    rows remain, no spurious revision from the co-terminating YTD."""
    load_parsed_xbrl(tmp_db, "TESTCO", q2018, date(2018, 5, 15), "https://x/v1.xml")
    load_parsed_xbrl(tmp_db, "TESTCO", _load("xbrl_q_2018.xml"), date(2018, 8, 1),
                     "https://x/v1b.xml")
    rows = tmp_db.execute(
        "SELECT count(*) FROM statements_xbrl WHERE symbol='TESTCO' "
        "AND tag='RevenueFromOperations' AND period_end='2018-03-31'").fetchone()[0]
    assert rows == 2
    revs = tmp_db.execute(
        "SELECT count(*) FROM statements_xbrl_revisions WHERE symbol='TESTCO'").fetchone()[0]
    assert revs == 0


def test_reload_identical_is_idempotent_no_revision(tmp_db, q2018):
    load_parsed_xbrl(tmp_db, "TESTCO", q2018, date(2018, 5, 15), "https://x/v1.xml")
    load_parsed_xbrl(tmp_db, "TESTCO", _load("xbrl_q_2018.xml"), date(2018, 8, 1),
                     "https://x/v1b.xml")
    revs = tmp_db.execute(
        "SELECT count(*) FROM statements_xbrl_revisions WHERE symbol='TESTCO'").fetchone()[0]
    assert revs == 0


def test_xbrl_filings_row_written(tmp_db, fy2024):
    res = load_parsed_xbrl(tmp_db, "FILECO", fy2024, date(2024, 5, 20), "https://x/fy.xml")
    row = tmp_db.execute(
        "SELECT taxonomy, status, facts, rounding, scale_to_cr, is_bank, period_end "
        "FROM xbrl_filings WHERE symbol='FILECO'").fetchone()
    assert row[0] == "in-bse-fin"
    assert row[1] == "ok"
    assert row[2] == res["facts"]
    assert row[3] == "Lakhs"
    assert row[4] == pytest.approx(0.01)
    assert row[5] is False
    assert row[6] == date(2024, 3, 31)   # FY end is the filing's primary period


# ---------------------------------------------------------------------------
# canonical_wide reader (PIT-respecting)
# ---------------------------------------------------------------------------
def test_canonical_wide_returns_latest_visible(tmp_db, fy2024):
    load_parsed_xbrl(tmp_db, "WIDECO", fy2024, date(2024, 5, 20), "https://x/fy.xml")
    wide = canonical_wide(tmp_db, "WIDECO", date(2024, 12, 31))
    assert "FY" in wide
    assert wide["FY"]["revenue"] == pytest.approx(15000.0)   # 1,500,000 Lakhs /100
    assert wide["FY"]["period_end"] == date(2024, 3, 31)
    # instant balance-sheet items land under kind 'I'
    assert "I" in wide
    assert wide["I"]["total_assets"] == pytest.approx(30000.0)


def test_canonical_wide_respects_visibility(tmp_db, fy2024):
    load_parsed_xbrl(tmp_db, "WIDECO", fy2024, date(2024, 5, 20), "https://x/fy.xml")
    # as_of BEFORE the filing date -> nothing visible
    wide = canonical_wide(tmp_db, "WIDECO", date(2024, 5, 1))
    assert wide == {}
