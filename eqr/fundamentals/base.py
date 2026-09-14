"""Metric framework + point-in-time input loader for the fundamentals layer.

Rules (from the Final Plan / methodology plan):
- a metric whose inputs are missing is UNKNOWN (value None), never zero;
- a metric that does not apply to the sector profile is NA;
- every metric carries provenance (source table, keys, inputs_as_of, note);
- all reads respect `visible_from <= as_of`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

import duckdb
import numpy as np
import pandas as pd

from ..config import settings
from ..store.pit import statements_as_of, shareholding_as_of

OK, UNKNOWN, NA = "OK", "UNKNOWN", "NA"

# every screener line item the fundamentals layer may read (superset of features/fundamental.py)
A_ITEMS = ["sales", "revenue", "expenses", "operating_profit", "financing_profit", "opm_pct", "other_income",
           "interest", "depreciation", "profit_before_tax", "tax_pct", "net_profit", "eps_in_rs",
           "dividend_payout_pct", "financing_margin_pct",
           "equity_capital", "reserves", "borrowings", "borrowing", "deposits", "other_liabilities",
           "total_liabilities", "fixed_assets", "cwip", "investments", "other_assets", "total_assets",
           "cash_from_operating_activity", "cash_from_investing_activity", "cash_from_financing_activity",
           "net_cash_flow", "free_cash_flow", "cfo_op",
           "roce_pct", "roe_pct", "debtor_days", "inventory_days", "days_payable", "cash_conversion_cycle",
           "working_capital_days"]
Q_ITEMS = ["sales", "revenue", "expenses", "operating_profit", "financing_profit", "opm_pct", "other_income",
           "interest", "depreciation", "profit_before_tax", "tax_pct", "net_profit", "eps_in_rs",
           "financing_margin_pct", "gross_npa_pct", "net_npa_pct"]


@dataclass
class Metric:
    name: str
    value: Optional[float]
    status: str = OK                      # OK | UNKNOWN | NA
    unit: str = "ratio"
    source_table: str = "statements"
    source_keys: str = ""
    inputs_as_of: Optional[date] = None
    note: str = ""

    def __post_init__(self):
        if self.value is not None and (isinstance(self.value, float) and not math.isfinite(self.value)):
            self.value, self.status = None, UNKNOWN
        if self.value is None and self.status == OK:
            self.status = UNKNOWN
        if self.value is not None:
            self.value = float(self.value)


class MetricSet:
    """Ordered bag of Metric keyed by name."""

    def __init__(self, metrics: Iterable[Metric] = ()):
        self._m: dict[str, Metric] = {}
        for m in metrics:
            self.add(m)

    def add(self, m: Metric) -> None:
        self._m[m.name] = m

    def extend(self, other: "MetricSet") -> None:
        for m in other:
            self.add(m)

    def __iter__(self):
        return iter(self._m.values())

    def __len__(self):
        return len(self._m)

    def __contains__(self, name: str) -> bool:
        return name in self._m

    def get(self, name: str) -> Optional[Metric]:
        return self._m.get(name)

    def v(self, name: str) -> Optional[float]:
        m = self._m.get(name)
        return None if m is None or m.status != OK else m.value

    def status(self, name: str) -> str:
        m = self._m.get(name)
        return UNKNOWN if m is None else m.status

    def rows(self, as_of: date, symbol: str, engine_version: str) -> list[dict]:
        return [{"as_of": as_of, "symbol": symbol, "metric": m.name, "value": m.value, "status": m.status,
                 "unit": m.unit, "source_table": m.source_table, "source_keys": m.source_keys,
                 "inputs_as_of": m.inputs_as_of, "note": m.note, "engine_version": engine_version}
                for m in self._m.values()]

    def as_dict(self) -> dict[str, Optional[float]]:
        return {m.name: (m.value if m.status == OK else None) for m in self._m.values()}


def unknown(name: str, note: str = "", unit: str = "ratio", source_table: str = "statements") -> Metric:
    return Metric(name, None, UNKNOWN, unit=unit, source_table=source_table, note=note)


def na(name: str, note: str = "not applicable to profile", unit: str = "ratio") -> Metric:
    return Metric(name, None, NA, unit=unit, note=note)


def ok(name: str, value: Optional[float], unit: str = "ratio", source_table: str = "statements",
       source_keys: str = "", inputs_as_of: Optional[date] = None, note: str = "") -> Metric:
    """OK when value is a finite number, UNKNOWN otherwise (never zero-fills)."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return Metric(name, None, UNKNOWN, unit=unit, source_table=source_table, source_keys=source_keys,
                      inputs_as_of=inputs_as_of, note=note or "input missing")
    return Metric(name, float(value), OK, unit=unit, source_table=source_table, source_keys=source_keys,
                  inputs_as_of=inputs_as_of, note=note)


# ----------------------------------------------------------------------------- inputs

@dataclass
class Inputs:
    symbol: str
    as_of: date
    industry: str
    profile: str                                 # from eqr.rating.sector.profile_for
    is_bank: bool
    is_financial: bool                           # BANK or NBFC_FIN
    annual: pd.DataFrame                         # index period_end asc; columns = A_ITEMS present
    quarterly: pd.DataFrame                      # index period_end asc; columns = Q_ITEMS present
    shareholding: pd.DataFrame                   # period_end, holder, pct (visible)
    feat: dict                                   # features row for (as_of, symbol), NaN -> None
    price: Optional[float]
    face_value: Optional[float]
    mcap_hist: pd.Series                         # split-invariant mcap (crore) at each annual period_end
    xbrl: dict = field(default_factory=dict)     # canonical_wide (r2); {} when absent
    deals: pd.DataFrame = field(default_factory=pd.DataFrame)
    announcements: pd.DataFrame = field(default_factory=pd.DataFrame)
    pledges: pd.DataFrame = field(default_factory=pd.DataFrame)
    insider: pd.DataFrame = field(default_factory=pd.DataFrame)
    credit: pd.DataFrame = field(default_factory=pd.DataFrame)
    surveillance: dict = field(default_factory=dict)   # {"in_gsm":0/1,"in_asm":0/1,"in_fo_ban":0/1}
    rf_pct: float = 6.0
    erp_pct: float = 5.5
    tax_rate: float = 0.25
    g_terminal: float = 0.05
    notes: list[str] = field(default_factory=list)

    # --- convenience accessors ---------------------------------------------------------
    def a(self, item: str, i: int = -1) -> Optional[float]:
        """Annual value at row i from the end (None when missing)."""
        return _at(self.annual, item, i)

    def q(self, item: str, i: int = -1) -> Optional[float]:
        return _at(self.quarterly, item, i)

    def a_series(self, item: str) -> pd.Series:
        if item not in self.annual.columns:
            return pd.Series(dtype=float)
        return self.annual[item].astype(float)

    def sales(self, i: int = -1) -> Optional[float]:
        v = self.a("sales", i)
        return v if v is not None else self.a("revenue", i)

    def op(self, i: int = -1) -> Optional[float]:
        v = self.a("operating_profit", i)
        return v if v is not None else self.a("financing_profit", i)

    def borrowings(self, i: int = -1) -> Optional[float]:
        v = self.a("borrowings", i)
        return v if v is not None else self.a("borrowing", i)

    def bve(self, i: int = -1) -> Optional[float]:
        eq, res = self.a("equity_capital", i), self.a("reserves", i)
        return None if eq is None or res is None else eq + res

    def n_years(self) -> int:
        return int(len(self.annual))

    def latest_period(self) -> Optional[date]:
        if len(self.annual) == 0:
            return None
        return pd.Timestamp(self.annual.index[-1]).date()

    def ttm(self, item: str) -> Optional[float]:
        """Sum of the last 4 visible quarters (gap <= 300 days) else latest annual."""
        qp = self.quarterly
        if item in qp.columns and len(qp) >= 4:
            rows = qp.iloc[-4:]
            span = (pd.Timestamp(rows.index[-1]) - pd.Timestamp(rows.index[0])).days
            vals = rows[item].astype(float)
            if span <= 300 and vals.notna().all():
                return float(vals.sum())
        return self.a(item)

    def ttm_sales(self) -> Optional[float]:
        v = self.ttm("sales")
        return v if v is not None else self.ttm("revenue")

    def ttm_op(self) -> Optional[float]:
        v = self.ttm("operating_profit")
        return v if v is not None else self.ttm("financing_profit")


def _at(df: pd.DataFrame, item: str, i: int) -> Optional[float]:
    if df is None or item not in df.columns or len(df) < abs(i):
        return None
    v = df[item].iloc[i]
    return None if pd.isna(v) else float(v)


def _pivot(df: pd.DataFrame, items: list[str]) -> dict[str, pd.DataFrame]:
    if df is None or df.empty:
        return {}
    df = df[df.line_item.isin(items)]
    out = {}
    for sym, g in df.groupby("symbol"):
        p = g.pivot_table(index="period_end", columns="line_item", values="value", aggfunc="first").sort_index()
        p.index = pd.to_datetime(p.index)
        # coalesce the singular/plural borrowings spelling (134 symbols carry `borrowing`)
        if "borrowing" in p.columns:
            if "borrowings" in p.columns:
                both = p["borrowings"].notna() & p["borrowing"].notna() & (p["borrowings"] != p["borrowing"])
                p.attrs["borrowing_conflict"] = bool(both.any())
                p["borrowings"] = p["borrowings"].fillna(p["borrowing"])
            else:
                p["borrowings"] = p["borrowing"]
        # every catalogue column exists (NaN when the source lacks it) so modules never KeyError
        missing = [c for c in items if c not in p.columns]
        if missing:
            p = p.reindex(columns=list(p.columns) + missing)
        out[sym] = p
    return out


def empty_frame(items: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=items, index=pd.DatetimeIndex([], name="period_end"), dtype=float)


def is_financial_industry(industry: Optional[str]) -> bool:
    from ..rating.sector import profile_for
    return profile_for(industry, False)[0] in ("BANK", "NBFC_FIN")


_SPLIT_RX = __import__('re').compile(r"split\s+(\d+(?:\.\d+)?)\s*->\s*(\d+(?:\.\d+)?)")


def face_value_history(con: duckdb.DuckDBPyConnection, symbol: str, fv_current: Optional[float],
                       as_of: date) -> list[tuple[date, float]]:
    """[(ex_date, face_value_before)] for split events visible on as_of, newest first.
    Splits change the face value (bonus issues do not); adj_factors.kind encodes the kind."""
    if fv_current is None or fv_current <= 0:
        return []
    rows = con.execute("SELECT ex_date, factor, kind FROM adj_factors WHERE symbol = ? AND ex_date <= ? "
                       "ORDER BY ex_date DESC", [symbol, as_of]).fetchall()
    out, fv = [], float(fv_current)
    for ex_date, factor, kind in rows:
        k = str(kind or "").lower()
        m = _SPLIT_RX.search(k)
        if m:                                            # "split 2->1; bonus 4:1" -> face value 2 before
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                fv = fv * a / b
                out.append((ex_date, fv))
        elif k.startswith("split") and factor and factor > 0:
            fv = fv / float(factor)
            out.append((ex_date, fv))
    return out


def mcap_series(con: duckdb.DuckDBPyConnection, symbol: str, annual: pd.DataFrame, fv_current: Optional[float],
                as_of: date) -> pd.Series:
    """Split-invariant historical market cap (crore) at each annual period_end <= as_of:
    raw close on/just before the period end x (equity_capital_y / face_value in force then).
    Raw closes pair with historical share counts, so bonuses and splits cancel out."""
    if annual is None or annual.empty or "equity_capital" not in annual.columns or not fv_current:
        return pd.Series(dtype=float)
    ends = [pd.Timestamp(d).date() for d in annual.index if pd.Timestamp(d).date() <= as_of]
    if not ends:
        return pd.Series(dtype=float)
    px = con.execute("""
        SELECT e.period_end, p.close FROM (SELECT unnest(?::DATE[]) AS period_end) e
        LEFT JOIN LATERAL (SELECT close FROM prices_daily WHERE symbol = ? AND series = 'EQ'
                           AND trade_date <= e.period_end AND trade_date >= e.period_end - INTERVAL 10 DAY
                           ORDER BY trade_date DESC LIMIT 1) p ON true""", [ends, symbol]).df()
    closes = {pd.Timestamp(r.period_end): r.close for r in px.itertuples()}
    splits = face_value_history(con, symbol, fv_current, as_of)
    out = {}
    for d in annual.index:
        dd = pd.Timestamp(d)
        if dd.date() > as_of:
            continue
        eq = annual.loc[d, "equity_capital"]
        close = closes.get(dd)
        if close is None or pd.isna(close) or pd.isna(eq):
            out[dd] = np.nan
            continue
        fv = float(fv_current)
        for ex_date, fv_before in splits:                # newest first
            if pd.Timestamp(ex_date) > dd:
                fv = fv_before
        out[dd] = float(close) * float(eq) / fv if fv > 0 else np.nan
    return pd.Series(out, dtype=float).sort_index()


def _feat_row(con: duckdb.DuckDBPyConnection, as_of: date, symbols: list[str]) -> dict[str, dict]:
    fd = con.execute("SELECT max(as_of) FROM features WHERE as_of <= ?", [as_of]).fetchone()[0]
    if fd is None:
        return {}
    df = con.execute("SELECT * FROM features WHERE as_of = ? AND symbol IN (" + ",".join("?" * len(symbols)) + ")",
                     [fd, *symbols]).df()
    out = {}
    for r in df.to_dict("records"):
        out[r["symbol"]] = {k: (None if (isinstance(v, float) and not math.isfinite(v)) or v is None or
                               (not isinstance(v, (str, date)) and pd.isna(v)) else v) for k, v in r.items()}
    return out


def _table_slice(con, table: str, symbols: list[str], as_of: date, date_col: str, sql_extra: str = "") -> pd.DataFrame:
    try:
        return con.execute(f"SELECT * FROM {table} WHERE symbol IN (" + ",".join("?" * len(symbols)) + ") "
                           f"AND {date_col} <= ? {sql_extra}", [*symbols, as_of]).df()
    except Exception:                                   # noqa: BLE001 - optional tables
        return pd.DataFrame()


def load_inputs(con: duckdb.DuckDBPyConnection, as_of: date, symbols: Optional[list[str]] = None,
                with_xbrl: bool = True) -> dict[str, Inputs]:
    """Point-in-time inputs for every symbol (default: the features universe on the latest
    feature date <= as_of)."""
    from ..rating.sector import profile_for
    s = settings()
    if symbols is None:
        fd = con.execute("SELECT max(as_of) FROM features WHERE as_of <= ?", [as_of]).fetchone()[0]
        symbols = [r[0] for r in con.execute("SELECT symbol FROM features WHERE as_of = ? ORDER BY symbol", [fd]).fetchall()] if fd else []
    if not symbols:
        return {}
    inst = con.execute("SELECT symbol, face_value, industry, sector FROM instruments WHERE symbol IN ("
                       + ",".join("?" * len(symbols)) + ")", symbols).df().set_index("symbol")
    stm = statements_as_of(con, as_of, symbols)
    a_all = stm[stm.stmt.isin(["pl_a", "bs_a", "cf_a", "ratios_a"])]
    a = _pivot(a_all, A_ITEMS)
    q = _pivot(stm[stm.stmt == "pl_q"], Q_ITEMS)
    sh = shareholding_as_of(con, as_of, symbols)
    if not sh.empty:
        sh["period_end"] = pd.to_datetime(sh["period_end"])
        sh = sh[sh.period_end <= pd.Timestamp(as_of)]
    feats = _feat_row(con, as_of, symbols)
    deals = _table_slice(con, "deals", symbols, as_of, "trade_date")
    ann = _table_slice(con, "announcements", symbols, as_of, "ann_dt")
    pledges = _table_slice(con, "pledges", symbols, as_of, "visible_from")
    insider = _table_slice(con, "insider_trades", symbols, as_of, "visible_from")
    credit = _table_slice(con, "credit_ratings", symbols, as_of, "visible_from")
    rf = float(getattr(s, "risk_free_pct", 6.0))
    erp = float(_env_float("EQR_ERP_PCT", 5.5))
    tax = float(_env_float("EQR_TAX_RATE_PCT", 25.0)) / 100
    g_t = float(_env_float("EQR_TERMINAL_GROWTH_PCT", 5.0)) / 100
    xbrl_wide = {}
    if with_xbrl:
        try:
            n = con.execute("SELECT count(*) FROM statements_xbrl").fetchone()[0]
        except Exception:                               # noqa: BLE001
            n = 0
        if n:
            from ..spine.xbrl import canonical_wide
            for sym in symbols:
                try:
                    xbrl_wide[sym] = canonical_wide(con, sym, as_of) or {}
                except Exception:                       # noqa: BLE001 - never block on XBRL
                    xbrl_wide[sym] = {}
    out: dict[str, Inputs] = {}
    for sym in symbols:
        ap = a.get(sym)
        ap = empty_frame(A_ITEMS) if ap is None else ap[ap.index <= pd.Timestamp(as_of)]
        qp = q.get(sym)
        qp = empty_frame(Q_ITEMS) if qp is None else qp[qp.index <= pd.Timestamp(as_of)]
        industry = None
        if sym in inst.index:
            industry = inst.industry.get(sym)
            if industry is None or (isinstance(industry, float) and pd.isna(industry)):
                industry = inst.sector.get(sym)
        industry = None if industry is None or (isinstance(industry, float) and pd.isna(industry)) else str(industry)
        has_deposits = len(ap) > 0 and "deposits" in ap.columns and pd.notna(ap["deposits"].iloc[-1])
        profile, notes = profile_for(industry, has_deposits)
        fv = float(inst.face_value.get(sym)) if sym in inst.index and pd.notna(inst.face_value.get(sym)) else None
        feat = feats.get(sym, {})
        price = feat.get("close")
        mh = mcap_series(con, sym, ap, fv, as_of) if len(ap) else pd.Series(dtype=float)
        if len(ap) and ap.attrs.get("borrowing_conflict"):
            notes = notes + ["borrowing_conflict"]
        out[sym] = Inputs(
            symbol=sym, as_of=as_of, industry=industry or "UNKNOWN", profile=profile,
            is_bank=profile == "BANK", is_financial=profile in ("BANK", "NBFC_FIN"),
            annual=ap, quarterly=qp, shareholding=sh[sh.symbol == sym] if not sh.empty else sh,
            feat=feat, price=price, face_value=fv, mcap_hist=mh, xbrl=xbrl_wide.get(sym, {}),
            deals=deals[deals.symbol == sym] if not deals.empty else deals,
            announcements=ann[ann.symbol == sym] if not ann.empty else ann,
            pledges=pledges[pledges.symbol == sym] if not pledges.empty else pledges,
            insider=insider[insider.symbol == sym] if not insider.empty else insider,
            credit=credit[credit.symbol == sym] if not credit.empty else credit,
            surveillance={"in_gsm": int(feat.get("in_gsm") or 0), "in_asm": int(feat.get("in_asm") or 0),
                          "in_fo_ban": int(feat.get("in_fo_ban") or 0)},
            rf_pct=rf, erp_pct=erp, tax_rate=tax, g_terminal=g_t, notes=list(notes))
    return out


def _env_float(name: str, default: float) -> float:
    import os
    v = os.environ.get(name)
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


# ----------------------------------------------------------------------------- cross-section helpers

def percentile_grouped(s: pd.Series, groups: pd.Series, min_group: int = 8) -> pd.Series:
    """0..100 percentile rank within group (>= min_group known values) else vs the whole
    universe; NaN stays NaN. Reuses the MAD winsorisation of features/xsection."""
    from ..features.xsection import winsorise
    x = winsorise(s.astype(float))
    out = pd.Series(np.nan, index=s.index, dtype=float)
    counts = x.groupby(groups).transform(lambda g: g.notna().sum())
    big = counts >= min_group
    if big.any():
        out[big] = x[big].groupby(groups[big]).rank(pct=True) * 100
    rest = ~big
    if rest.any():
        out[rest] = (x.rank(pct=True) * 100)[rest]
    return out
