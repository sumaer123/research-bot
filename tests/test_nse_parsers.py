import io
import zipfile
from datetime import date

from eqr.spine import nse_archives as na
from tests.conftest import FIXTURES


def _zip(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", csv_text)
    return buf.getvalue()


def test_sec_full():
    df = na.parse_sec_full((FIXTURES / "sec_full_sample.csv").read_text())
    assert set(df.columns) == set(na.PRICE_COLS)
    r = df[df.symbol == "RELIANCE"].iloc[0]
    assert r.trade_date == date(2026, 9, 11) and r.series == "EQ"
    assert r.turnover_inr > 1e8 and 0 < r.deliv_pct <= 100 and r.vwap > 0


def test_old_bhav_filters_non_equity_series():
    df = na.parse_old_bhav(_zip((FIXTURES / "old_bhav_sample.csv").read_text()))
    assert "1003GS2019" not in set(df.symbol)             # GS series dropped
    r = df[df.symbol == "20MICRONS"].iloc[0]
    assert r.trade_date == date(2019, 4, 1) and r["isin"] == "INE144J01027" and r.prev_close == 38.2


def test_udiff():
    df = na.parse_udiff(_zip((FIXTURES / "udiff_sample.csv").read_text()))
    assert "SGBMAY28" not in set(df.symbol)
    r = df[df.symbol == "SAMBHAAV"].iloc[0]
    assert r.series == "BE" and r.trade_date == date(2024, 1, 8) and r.close == 4.25


def test_mto_and_merge():
    mto = na.parse_mto((FIXTURES / "mto_sample.dat").read_text())
    assert mto[mto.symbol == "20MICRONS"].deliv_pct.iloc[0] == 83.63
    px = na.parse_old_bhav(_zip((FIXTURES / "old_bhav_sample.csv").read_text()))
    merged = na.merge_delivery(px, mto)
    assert merged[merged.symbol == "20MICRONS"].deliv_qty.iloc[0] == 58660


def test_index_close():
    df = na.parse_index_close((FIXTURES / "index_close_sample.csv").read_text())
    names = set(df.index_name)
    assert {"Nifty 50", "Nifty 500", "India VIX"} <= names
    vix = df[df.index_name == "India VIX"].iloc[0]
    assert vix.close == 12.29 and vix.pe != vix.pe                 # '-' -> NaN


def test_equity_l_ban_deals_n500():
    inst = na.parse_equity_l((FIXTURES / "equity_l_sample.csv").read_text(), date(2026, 9, 14))
    r = inst[inst.symbol == "20MICRONS"].iloc[0]
    assert r.face_value == 5 and r.listing_date == date(2008, 10, 6)
    assert na.parse_fo_ban((FIXTURES / "fo_ban_sample.csv").read_text())[:2] == ["BANDHANBNK", "INOXWIND"]
    deals = na.parse_deals((FIXTURES / "bulk_sample.csv").read_text(), "bulk")
    assert deals.iloc[0].side == "BUY" and deals.iloc[0].kind == "bulk"
    n500 = na.parse_nifty500_list((FIXTURES / "nifty500_sample.csv").read_text())
    assert n500.iloc[0].industry == "Financial Services"


def test_parse_error_on_wrong_columns():
    import pytest
    with pytest.raises(na.ParseError):
        na.parse_sec_full("A,B\n1,2\n")


def test_urls():
    assert na.url_old_bhav(date(2019, 4, 1)).endswith("/2019/APR/cm01APR2019bhav.csv.zip")
    assert na.url_udiff(date(2024, 1, 8)).endswith("BhavCopy_NSE_CM_0_0_0_20240108_F_0000.csv.zip")
    assert na.url_mto(date(2019, 4, 1)).endswith("MTO_01042019.DAT")
