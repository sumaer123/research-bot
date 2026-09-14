"""Tests for T1.2: XBRL URLs in results_calendar feeds and fill_xbrl_urls.

All tests are network-free: NseApi is replaced with a MagicMock whose
get_json side-effect returns pre-canned JSON payloads.
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from eqr.spine.http import FetchResult
from eqr.spine.nse_api import (
    _xbrl_or_none,
    fetch_financial_results,
    fetch_integrated_results,
    fill_xbrl_urls,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(js) -> tuple:
    """Return a (FetchResult, json) pair as get_json would."""
    res = FetchResult(source="test", key="test", status="ok")
    return res, js


def _make_api(payload) -> MagicMock:
    """Build a fake NseApi that always returns `payload` regardless of path/params."""
    api = MagicMock()
    api.get_json.return_value = _ok(payload)
    return api


def _legacy_row(
    symbol="RELIANCE",
    to_date="30-Jun-2025",
    filing_date="15-Jul-2025 10:00:00",
    xbrl="https://archives.nseindia.com/corporate/xbrl/RELIANCE.xml",
    consolidated="Yes",
) -> dict:
    return {
        "symbol": symbol,
        "toDate": to_date,
        "filingDate": filing_date,
        "broadCastDate": filing_date,
        "audited": "Yes",
        "consolidated": consolidated,
        "xbrl": xbrl,
    }


def _ifr_row(
    symbol="INFY",
    qe_date="30-Jun-2025",
    broadcast_date="15-Jul-2025 10:00:00",
    xbrl="https://archives.nseindia.com/corporate/xbrl/INFY.xml",
    ixbrl=None,
    seq_id="SEQ123",
    type_sub="XBRL",
    consolidated="Yes",
) -> dict:
    return {
        "symbol": symbol,
        "qe_Date": qe_date,
        "broadcast_Date": broadcast_date,
        "audited": "Yes",
        "consolidated": consolidated,
        "xbrl": xbrl,
        "ixbrl": ixbrl,
        "seq_Id": seq_id,
        "type_Sub": type_sub,
    }


# ---------------------------------------------------------------------------
# _xbrl_or_none
# ---------------------------------------------------------------------------

def test_xbrl_or_none_real_url():
    url = "https://archives.nseindia.com/corporate/xbrl/RELIANCE_2025_Q1.xml"
    assert _xbrl_or_none(url) == url


def test_xbrl_or_none_dash():
    assert _xbrl_or_none("-") is None


def test_xbrl_or_none_slash_dash_placeholder():
    assert _xbrl_or_none("https://archives.nseindia.com/corporate/xbrl/-") is None


def test_xbrl_or_none_none_input():
    assert _xbrl_or_none(None) is None


def test_xbrl_or_none_empty_string():
    assert _xbrl_or_none("") is None


# ---------------------------------------------------------------------------
# fetch_financial_results — legacy feed
# ---------------------------------------------------------------------------

def test_fetch_financial_results_emits_xbrl_columns():
    api = _make_api([_legacy_row()])
    df = fetch_financial_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert "xbrl_url" in df.columns
    assert "seq_id" in df.columns
    assert "type_sub" in df.columns


def test_fetch_financial_results_real_xbrl_url():
    row = _legacy_row()
    api = _make_api([row])
    df = fetch_financial_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert df.iloc[0]["xbrl_url"] == row["xbrl"]


def test_fetch_financial_results_seq_id_type_sub_are_none():
    api = _make_api([_legacy_row()])
    df = fetch_financial_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert df.iloc[0]["seq_id"] is None
    assert df.iloc[0]["type_sub"] is None


def test_fetch_financial_results_dash_placeholder_to_none():
    api = _make_api([_legacy_row(xbrl="-")])
    df = fetch_financial_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert df.iloc[0]["xbrl_url"] is None


def test_fetch_financial_results_slash_dash_placeholder_to_none():
    url = "https://archives.nseindia.com/corporate/xbrl/-"
    api = _make_api([_legacy_row(xbrl=url)])
    df = fetch_financial_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert df.iloc[0]["xbrl_url"] is None


# ---------------------------------------------------------------------------
# fetch_integrated_results — IFR feed
# ---------------------------------------------------------------------------

def test_fetch_integrated_results_emits_xbrl_columns():
    api = _make_api({"data": [_ifr_row()]})
    df = fetch_integrated_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert "xbrl_url" in df.columns
    assert "seq_id" in df.columns
    assert "type_sub" in df.columns


def test_fetch_integrated_results_xbrl_url_and_ids():
    row = _ifr_row()
    api = _make_api({"data": [row]})
    df = fetch_integrated_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert df.iloc[0]["xbrl_url"] == row["xbrl"]
    assert df.iloc[0]["seq_id"] == "SEQ123"
    assert df.iloc[0]["type_sub"] == "XBRL"


def test_fetch_integrated_results_fallback_to_ixbrl():
    """When xbrl is absent/None, the ixbrl URL is used instead."""
    ixbrl_url = "https://archives.nseindia.com/corporate/xbrl/INFY_ix.xml"
    row = _ifr_row(xbrl=None, ixbrl=ixbrl_url)
    api = _make_api({"data": [row]})
    df = fetch_integrated_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert df.iloc[0]["xbrl_url"] == ixbrl_url


def test_fetch_integrated_results_placeholder_to_none():
    row = _ifr_row(xbrl="-", ixbrl=None)
    api = _make_api({"data": [row]})
    df = fetch_integrated_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert df.iloc[0]["xbrl_url"] is None


def test_fetch_integrated_results_slash_dash_placeholder_to_none():
    row = _ifr_row(xbrl="https://archives.nseindia.com/corporate/xbrl/-", ixbrl=None)
    api = _make_api({"data": [row]})
    df = fetch_integrated_results(api, date(2025, 4, 1), date(2025, 6, 30))
    assert df.iloc[0]["xbrl_url"] is None


# ---------------------------------------------------------------------------
# fill_xbrl_urls — first-seen filing_dt preserved; no overwrite
# ---------------------------------------------------------------------------

def test_fill_xbrl_urls_fills_null_and_preserves_filing_dt(tmp_db):
    """fill_xbrl_urls fills a NULL xbrl_url and must NOT alter the existing filing_dt."""
    original_dt = datetime(2025, 7, 10, 8, 0, 0)
    tmp_db.execute(
        "INSERT INTO results_calendar (symbol, period_end, consolidated, filing_dt, audited, period, source) "
        "VALUES ('RELIANCE', '2025-06-30', 'Yes', ?, 'Yes', 'Quarterly', 'nse')",
        [original_dt],
    )

    xbrl_url = "https://archives.nseindia.com/corporate/xbrl/RELIANCE.xml"
    api = _make_api([_legacy_row(xbrl=xbrl_url)])

    from eqr.store import new_run
    run_id = new_run(tmp_db, "test", "xbrl fill")
    result = fill_xbrl_urls(tmp_db, api, run_id, date(2025, 4, 1), date(2025, 6, 30))

    assert isinstance(result, dict)
    row = tmp_db.execute(
        "SELECT xbrl_url, filing_dt FROM results_calendar "
        "WHERE symbol='RELIANCE' AND period_end='2025-06-30' AND consolidated='Yes'"
    ).fetchone()
    assert row[0] == xbrl_url, "xbrl_url should be filled from the feed"
    assert row[1] == original_dt, "filing_dt must not be changed by fill_xbrl_urls"


def test_fill_xbrl_urls_does_not_overwrite_existing(tmp_db):
    """fill_xbrl_urls must not overwrite a row that already has xbrl_url set."""
    original_xbrl = "https://original.nseindia.com/existing.xml"
    original_dt = datetime(2025, 7, 10, 8, 0, 0)
    tmp_db.execute(
        "INSERT INTO results_calendar "
        "(symbol, period_end, consolidated, filing_dt, audited, period, source, xbrl_url) "
        "VALUES ('RELIANCE', '2025-06-30', 'Yes', ?, 'Yes', 'Quarterly', 'nse', ?)",
        [original_dt, original_xbrl],
    )

    # Feed returns a *different* URL — should not clobber the existing one
    new_xbrl = "https://new.nseindia.com/replacement.xml"
    api = _make_api([_legacy_row(xbrl=new_xbrl)])

    from eqr.store import new_run
    run_id = new_run(tmp_db, "test", "xbrl no-overwrite")
    fill_xbrl_urls(tmp_db, api, run_id, date(2025, 4, 1), date(2025, 6, 30))

    row = tmp_db.execute(
        "SELECT xbrl_url FROM results_calendar "
        "WHERE symbol='RELIANCE' AND period_end='2025-06-30' AND consolidated='Yes'"
    ).fetchone()
    assert row[0] == original_xbrl, "existing xbrl_url must never be overwritten"
