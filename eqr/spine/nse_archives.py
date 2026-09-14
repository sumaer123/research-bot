"""NSE archive files (no cookies): bhavcopy in three formats, MTO delivery, index
closes, instrument master, F&O ban, bulk/block deals. URL builders + strict parsers.

A parser that does not find its expected columns raises ParseError; the refresh
orchestrator turns that into a logged 'error' rather than guessing."""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime
from typing import Optional

import pandas as pd

ARCH = "https://nsearchives.nseindia.com"
EQUITY_SERIES = ("EQ", "BE", "BZ", "SM", "ST")
UDIFF_START = date(2024, 1, 8)          # first UDiFF bhavcopy observed
OLD_END = date(2024, 7, 31)             # old-format bhavcopy discontinued mid-2024

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


class ParseError(ValueError):
    pass


# ------------------------------------------------------------------ URLs ----

def url_old_bhav(d: date) -> str:
    return f"{ARCH}/content/historical/EQUITIES/{d.year}/{MONTHS[d.month - 1]}/cm{d.day:02d}{MONTHS[d.month - 1]}{d.year}bhav.csv.zip"


def url_udiff(d: date) -> str:
    return f"{ARCH}/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def url_sec_full(d: date) -> str:
    return f"{ARCH}/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"


def url_mto(d: date) -> str:
    return f"{ARCH}/archives/equities/mto/MTO_{d:%d%m%Y}.DAT"


def url_index_close(d: date) -> str:
    return f"{ARCH}/content/indices/ind_close_all_{d:%d%m%Y}.csv"


URL_EQUITY_L = f"{ARCH}/content/equities/EQUITY_L.csv"
URL_FO_BAN = f"{ARCH}/content/fo/fo_secban.csv"
URL_BULK = f"{ARCH}/content/equities/bulk.csv"
URL_BLOCK = f"{ARCH}/content/equities/block.csv"
URL_NIFTY500 = f"{ARCH}/content/indices/ind_nifty500list.csv"
URL_ETF_LIST = f"{ARCH}/content/equities/eq_etfseclist.csv"


# --------------------------------------------------------------- helpers ----

def _num(x) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip().replace(",", "")
    if s in ("", "-", "NA", "nan", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(x) -> Optional[int]:
    v = _num(x)
    return None if v is None else int(round(v))


def _unzip_single_csv(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ParseError("zip without csv")
        return z.read(names[0]).decode("utf-8", errors="replace")


def _read_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), dtype=str, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    return df


def _require(df: pd.DataFrame, cols: list[str], what: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ParseError(f"{what}: missing columns {missing}")


PRICE_COLS = ["trade_date", "symbol", "series", "isin", "prev_close", "open", "high", "low",
              "close", "last", "vwap", "volume", "turnover_inr", "trades", "deliv_qty",
              "deliv_pct", "source"]


def _finish_prices(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df = df[df["series"].isin(EQUITY_SERIES)].copy()
    df["symbol"] = df["symbol"].str.strip()
    df["source"] = source
    for c in PRICE_COLS:
        if c not in df.columns:
            df[c] = None
    df = df[PRICE_COLS]
    df = df.dropna(subset=["close"])
    return df.reset_index(drop=True)


# --------------------------------------------------------------- parsers ----

def parse_old_bhav(blob: bytes) -> pd.DataFrame:
    df = _read_csv(_unzip_single_csv(blob))
    _require(df, ["SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "LAST", "PREVCLOSE",
                  "TOTTRDQTY", "TOTTRDVAL", "TIMESTAMP", "ISIN"], "old bhavcopy")
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(df["TIMESTAMP"].str.strip(), format="%d-%b-%Y").dt.date,
        "symbol": df["SYMBOL"], "series": df["SERIES"].str.strip(), "isin": df["ISIN"].str.strip(),
        "prev_close": df["PREVCLOSE"].map(_num), "open": df["OPEN"].map(_num),
        "high": df["HIGH"].map(_num), "low": df["LOW"].map(_num), "close": df["CLOSE"].map(_num),
        "last": df["LAST"].map(_num), "volume": df["TOTTRDQTY"].map(_int),
        "turnover_inr": df["TOTTRDVAL"].map(_num),
        "trades": df["TOTALTRADES"].map(_int) if "TOTALTRADES" in df.columns else None,
    })
    return _finish_prices(out, "old_bhav")


def parse_udiff(blob: bytes) -> pd.DataFrame:
    df = _read_csv(_unzip_single_csv(blob))
    _require(df, ["TradDt", "TckrSymb", "SctySrs", "ISIN", "OpnPric", "HghPric", "LwPric",
                  "ClsPric", "LastPric", "PrvsClsgPric", "TtlTradgVol", "TtlTrfVal"], "udiff bhavcopy")
    df = df[df["Sgmt"].str.strip() == "CM"] if "Sgmt" in df.columns else df
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(df["TradDt"].str.strip(), format="%Y-%m-%d").dt.date,
        "symbol": df["TckrSymb"], "series": df["SctySrs"].fillna("").str.strip(),
        "isin": df["ISIN"].str.strip(),
        "prev_close": df["PrvsClsgPric"].map(_num), "open": df["OpnPric"].map(_num),
        "high": df["HghPric"].map(_num), "low": df["LwPric"].map(_num),
        "close": df["ClsPric"].map(_num), "last": df["LastPric"].map(_num),
        "volume": df["TtlTradgVol"].map(_int), "turnover_inr": df["TtlTrfVal"].map(_num),
        "trades": df["TtlNbOfTxsExctd"].map(_int) if "TtlNbOfTxsExctd" in df.columns else None,
    })
    return _finish_prices(out, "udiff")


def parse_sec_full(text: str) -> pd.DataFrame:
    df = _read_csv(text)
    _require(df, ["SYMBOL", "SERIES", "DATE1", "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE",
                  "LOW_PRICE", "LAST_PRICE", "CLOSE_PRICE", "AVG_PRICE", "TTL_TRD_QNTY",
                  "TURNOVER_LACS", "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER"], "sec_bhavdata_full")
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(df["DATE1"].str.strip(), format="%d-%b-%Y").dt.date,
        "symbol": df["SYMBOL"], "series": df["SERIES"].str.strip(), "isin": None,
        "prev_close": df["PREV_CLOSE"].map(_num), "open": df["OPEN_PRICE"].map(_num),
        "high": df["HIGH_PRICE"].map(_num), "low": df["LOW_PRICE"].map(_num),
        "close": df["CLOSE_PRICE"].map(_num), "last": df["LAST_PRICE"].map(_num),
        "vwap": df["AVG_PRICE"].map(_num), "volume": df["TTL_TRD_QNTY"].map(_int),
        "turnover_inr": df["TURNOVER_LACS"].map(_num).mul(1e5),
        "trades": df["NO_OF_TRADES"].map(_int), "deliv_qty": df["DELIV_QTY"].map(_int),
        "deliv_pct": df["DELIV_PER"].map(_num),
    })
    return _finish_prices(out, "sec_full")


def parse_mto(text: str) -> pd.DataFrame:
    rows = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7 and parts[0] == "20":
            rows.append({"symbol": parts[2], "series": parts[3], "deliv_qty": _int(parts[5]),
                         "deliv_pct": _num(parts[6])})
    if not rows:
        raise ParseError("MTO: no record-type-20 rows")
    return pd.DataFrame(rows)


def parse_index_close(text: str) -> pd.DataFrame:
    df = _read_csv(text)
    _require(df, ["Index Name", "Index Date", "Closing Index Value"], "ind_close_all")
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(df["Index Date"].str.strip(), format="%d-%m-%Y").dt.date,
        "index_name": df["Index Name"].str.strip(),
        "open": df.get("Open Index Value", pd.Series(dtype=str)).map(_num),
        "high": df.get("High Index Value", pd.Series(dtype=str)).map(_num),
        "low": df.get("Low Index Value", pd.Series(dtype=str)).map(_num),
        "close": df["Closing Index Value"].map(_num),
        "points_change": df.get("Points Change", pd.Series(dtype=str)).map(_num),
        "pct_change": df.get("Change(%)", pd.Series(dtype=str)).map(_num),
        "volume": df.get("Volume", pd.Series(dtype=str)).map(_num),
        "turnover_cr": df.get("Turnover (Rs. Cr.)", pd.Series(dtype=str)).map(_num),
        "pe": df.get("P/E", pd.Series(dtype=str)).map(_num),
        "pb": df.get("P/B", pd.Series(dtype=str)).map(_num),
        "div_yield": df.get("Div Yield", pd.Series(dtype=str)).map(_num),
    })
    out = out.dropna(subset=["close"]).drop_duplicates(subset=["trade_date", "index_name"], keep="first")
    return out.reset_index(drop=True)


def parse_equity_l(text: str, as_of: Optional[date] = None) -> pd.DataFrame:
    df = _read_csv(text)
    _require(df, ["SYMBOL", "NAME OF COMPANY", "SERIES", "DATE OF LISTING", "ISIN NUMBER", "FACE VALUE"],
             "EQUITY_L")
    out = pd.DataFrame({
        "symbol": df["SYMBOL"].str.strip(), "name": df["NAME OF COMPANY"].str.strip(),
        "series": df["SERIES"].str.strip(),
        "isin": df["ISIN NUMBER"].str.strip(),
        "listing_date": pd.to_datetime(df["DATE OF LISTING"].str.strip(), format="%d-%b-%Y",
                                       errors="coerce").dt.date,
        "face_value": df["FACE VALUE"].map(_num),
        "paid_up_value": df.get("PAID UP VALUE", pd.Series(dtype=str)).map(_num),
        "market_lot": df.get("MARKET LOT", pd.Series(dtype=str)).map(_int),
        "as_of": as_of or date.today(),
    })
    return out


def parse_fo_ban(text: str) -> list[str]:
    syms = []
    for line in text.splitlines():
        m = re.match(r"^\s*\d+\s*,\s*([A-Z0-9&\-]+)\s*$", line.strip())
        if m:
            syms.append(m.group(1))
    return syms


def parse_deals(text: str, kind: str) -> pd.DataFrame:
    df = _read_csv(text)
    _require(df, ["Date", "Symbol", "Client Name", "Buy/Sell", "Quantity Traded",
                  "Trade Price / Wght. Avg. Price"], f"{kind} deals")
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(df["Date"].str.strip(), format="%d-%b-%Y").dt.date,
        "symbol": df["Symbol"].str.strip(), "kind": kind,
        "client": df["Client Name"].str.strip().str.slice(0, 120),
        "side": df["Buy/Sell"].str.strip().str.upper(),
        "qty": df["Quantity Traded"].map(_int),
        "price": df["Trade Price / Wght. Avg. Price"].map(_num),
    })
    return out.dropna(subset=["qty", "price"]).reset_index(drop=True)


def parse_nifty500_list(text: str) -> pd.DataFrame:
    df = _read_csv(text)
    _require(df, ["Symbol", "Industry"], "ind_nifty500list")
    return pd.DataFrame({"symbol": df["Symbol"].str.strip(), "industry": df["Industry"].str.strip(),
                         "isin": df.get("ISIN Code", pd.Series(dtype=str)).str.strip()})


def merge_delivery(prices: pd.DataFrame, mto: Optional[pd.DataFrame]) -> pd.DataFrame:
    if mto is None or mto.empty:
        return prices
    m = mto.drop_duplicates(subset=["symbol", "series"]).set_index(["symbol", "series"])
    idx = pd.MultiIndex.from_arrays([prices["symbol"], prices["series"]])
    prices = prices.copy()
    prices["deliv_qty"] = m["deliv_qty"].reindex(idx).values
    prices["deliv_pct"] = m["deliv_pct"].reindex(idx).values
    return prices


def parse_etf_list(text: str, as_of: Optional[date] = None) -> pd.DataFrame:
    df = _read_csv(text)
    _require(df, ["Symbol"], "eq_etfseclist")
    return pd.DataFrame({"symbol": df["Symbol"].str.strip(),
                         "underlying": df.get("Underlying Asset", pd.Series(dtype=str)).astype(str).str.strip().str.slice(0, 120),
                         "listing_date": pd.to_datetime(df.get("DateofListing", pd.Series(dtype=str)), format="%d-%b-%y", errors="coerce").dt.date,
                         "as_of": as_of or date.today()})
