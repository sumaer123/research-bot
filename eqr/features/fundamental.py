"""As-of fundamental features from the long-format statements table.

Inputs are screener.in line items (crores). Missing inputs give NaN, never zero.
Piotroski here is the 7-signal subset the source supports; Altman Z'' uses the
documented approximations (see spec section 5)."""
from __future__ import annotations

from datetime import date
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from ..store.pit import statements_as_of, shareholding_as_of

Q_ITEMS = ["sales", "revenue", "expenses", "operating_profit", "financing_profit", "other_income", "interest",
           "depreciation", "profit_before_tax", "net_profit", "eps_in_rs"]
A_ITEMS = ["sales", "revenue", "operating_profit", "financing_profit", "other_income", "interest", "depreciation",
           "net_profit", "dividend_payout_pct", "equity_capital", "reserves", "borrowings", "deposits",
           "other_liabilities", "total_liabilities", "fixed_assets", "cwip", "investments", "other_assets",
           "total_assets", "cash_from_operating_activity", "cash_from_investing_activity",
           "free_cash_flow", "roce_pct", "debtor_days", "working_capital_days"]


def _pivot(df: pd.DataFrame, items: list[str]) -> dict[str, pd.DataFrame]:
    """symbol -> DataFrame(index=period_end asc, columns=line items)."""
    if df.empty:
        return {}
    df = df[df.line_item.isin(items)]
    out = {}
    for sym, g in df.groupby("symbol"):
        p = g.pivot_table(index="period_end", columns="line_item", values="value", aggfunc="first").sort_index()
        out[sym] = p
    return out


def _g(p: pd.DataFrame, item: str, i: int = -1) -> float:
    """Value at row i (from the end) or NaN."""
    if item not in p.columns or len(p) < abs(i):
        return np.nan
    v = p[item].iloc[i]
    return float(v) if pd.notna(v) else np.nan


def _sales(p: pd.DataFrame, i: int = -1) -> float:
    v = _g(p, "sales", i)
    return v if pd.notna(v) else _g(p, "revenue", i)


def _op(p: pd.DataFrame, i: int = -1) -> float:
    v = _g(p, "operating_profit", i)
    return v if pd.notna(v) else _g(p, "financing_profit", i)


def _ttm(p: pd.DataFrame, item_fn, offset: int = 0) -> float:
    """Sum of 4 quarters ending `offset` quarters before the latest; NaN if the 4
    periods do not span <= 300 days (gaps) or fewer than 4 exist."""
    n = len(p)
    if n < 4 + offset:
        return np.nan
    rows = p.iloc[n - 4 - offset:n - offset]
    span = (pd.Timestamp(rows.index[-1]) - pd.Timestamp(rows.index[0])).days
    if span > 300:
        return np.nan
    vals = [item_fn(rows, i) for i in range(-4, 0)]
    if any(pd.isna(v) for v in vals):
        return np.nan
    return float(sum(vals))


def fundamental_features(con: duckdb.DuckDBPyConnection, as_of: date, symbols: list[str],
                         face_values: dict[str, float], closes: pd.Series) -> pd.DataFrame:
    q = _pivot(statements_as_of(con, as_of, symbols, stmt="pl_q"), Q_ITEMS)
    a_all = statements_as_of(con, as_of, symbols)
    a_all = a_all[a_all.stmt.isin(["pl_a", "bs_a", "cf_a", "ratios_a"])]
    a = _pivot(a_all, A_ITEMS)
    sh = shareholding_as_of(con, as_of, symbols)
    rows = []
    for sym in symbols:
        r: dict = {"symbol": sym}
        qp = q.get(sym)
        if qp is not None and len(qp):
            qp = qp[qp.index <= pd.Timestamp(as_of)]
        if qp is not None and len(qp):
            r["stmt_age_days"] = (pd.Timestamp(as_of) - pd.Timestamp(qp.index[-1])).days
            s0, s1 = _ttm(qp, _sales), _ttm(qp, _sales, 4)
            p0, p1 = _ttm(qp, lambda p, i: _g(p, "net_profit", i)), _ttm(qp, lambda p, i: _g(p, "net_profit", i), 4)
            op0, op1 = _ttm(qp, _op), _ttm(qp, _op, 4)
            r["sales_ttm"], r["pat_ttm"] = s0, p0
            r["sales_yoy_ttm"] = s0 / s1 - 1 if s1 and s1 > 0 else np.nan
            r["pat_yoy_ttm"] = (p0 - p1) / abs(p1) if p1 and p1 != 0 else np.nan
            r["opm_ttm"] = op0 / s0 if s0 and s0 > 0 and pd.notna(op0) else np.nan
            opm1 = op1 / s1 if s1 and s1 > 0 and pd.notna(op1) else np.nan
            r["opm_chg_1y"] = r["opm_ttm"] - opm1 if pd.notna(r["opm_ttm"]) and pd.notna(opm1) else np.nan
            it = _ttm(qp, lambda p, i: _g(p, "interest", i))
            dep = _ttm(qp, lambda p, i: _g(p, "depreciation", i))
            oi = _ttm(qp, lambda p, i: _g(p, "other_income", i))
            ebit = op0 - dep + (oi if pd.notna(oi) else 0) if pd.notna(op0) and pd.notna(dep) else np.nan
            r["int_cover"] = ebit / it if it and it > 0 and pd.notna(ebit) else np.nan
            r["eps_ttm"] = _ttm(qp, lambda p, i: _g(p, "eps_in_rs", i))
        ap = a.get(sym)
        if ap is not None and len(ap):
            ap = ap[ap.index <= pd.Timestamp(as_of)]
        if ap is not None and len(ap):
            # annual fallback for the trailing metrics when no quarterly statement is visible
            # (screener carries 13 quarters, 12 fiscal years): "TTM" then means the last fiscal year
            if pd.isna(r.get("pat_ttm", np.nan)):
                s_now, s_prev = _sales(ap, -1), _sales(ap, -2)
                ni_now, ni_prev = _g(ap, "net_profit", -1), _g(ap, "net_profit", -2)
                op_now, op_prev = _op(ap, -1), _op(ap, -2)
                r["sales_ttm"], r["pat_ttm"] = s_now, ni_now
                r["sales_yoy_ttm"] = s_now / s_prev - 1 if s_prev and s_prev > 0 and pd.notna(s_now) else np.nan
                r["pat_yoy_ttm"] = (ni_now - ni_prev) / abs(ni_prev) if ni_prev and ni_prev != 0 and pd.notna(ni_now) else np.nan
                r["opm_ttm"] = op_now / s_now if s_now and s_now > 0 and pd.notna(op_now) else np.nan
                opm_prev = op_prev / s_prev if s_prev and s_prev > 0 and pd.notna(op_prev) else np.nan
                r["opm_chg_1y"] = r["opm_ttm"] - opm_prev if pd.notna(r["opm_ttm"]) and pd.notna(opm_prev) else np.nan
                it, dep, oi = _g(ap, "interest"), _g(ap, "depreciation"), _g(ap, "other_income")
                ebit = op_now - dep + (oi if pd.notna(oi) else 0) if pd.notna(op_now) and pd.notna(dep) else np.nan
                r["int_cover"] = ebit / it if it and it > 0 and pd.notna(ebit) else np.nan
                r["eps_ttm"] = _g(ap, "eps_in_rs")
                if pd.isna(r.get("stmt_age_days", np.nan)):
                    r["stmt_age_days"] = (pd.Timestamp(as_of) - pd.Timestamp(ap.index[-1])).days
            eq = _g(ap, "equity_capital"); res_ = _g(ap, "reserves"); ni = _g(ap, "net_profit")
            ta = _g(ap, "total_assets"); bor = _g(ap, "borrowings"); cfo = _g(ap, "cash_from_operating_activity")
            bve = eq + res_ if pd.notna(eq) and pd.notna(res_) else np.nan
            is_bank = "deposits" in ap.columns and pd.notna(_g(ap, "deposits"))
            r["roe"] = ni / bve if bve and bve > 0 and pd.notna(ni) else np.nan
            r["roce"] = _g(ap, "roce_pct") / 100 if pd.notna(_g(ap, "roce_pct")) else np.nan
            r["debt_equity"] = np.nan if is_bank else (bor / bve if bve and bve > 0 and pd.notna(bor) else np.nan)
            r["accruals"] = np.nan if is_bank else ((ni - cfo) / ta if ta and ta > 0 and pd.notna(ni) and pd.notna(cfo) else np.nan)
            r["fcf_ttm"] = np.nan if is_bank else _g(ap, "free_cash_flow")
            s_now, s_3 = _sales(ap, -1), _sales(ap, -4)
            r["sales_cagr_3y"] = (s_now / s_3) ** (1 / 3) - 1 if s_now and s_3 and s_now > 0 and s_3 > 0 else np.nan
            p_now, p_3 = ni, _g(ap, "net_profit", -4)
            r["pat_cagr_3y"] = (p_now / p_3) ** (1 / 3) - 1 if p_now and p_3 and p_now > 0 and p_3 > 0 else np.nan
            r.update(_piotroski(ap, is_bank))
            r["altman_zpp"] = np.nan if is_bank else _altman(ap)
            fv = face_values.get(sym)
            shares_cr = eq / fv if fv and fv > 0 and pd.notna(eq) else np.nan
            r["shares_cr"] = shares_cr
            close = closes.get(sym, np.nan)
            mcap = close * shares_cr if pd.notna(close) and pd.notna(shares_cr) else np.nan
            r["mcap_cr"] = mcap
            pat = r.get("pat_ttm", np.nan)
            r["pe_ttm"] = mcap / pat if pd.notna(mcap) and pd.notna(pat) and pat > 0 else np.nan
            r["earnings_yield"] = pat / mcap if pd.notna(mcap) and mcap > 0 and pd.notna(pat) else np.nan
            r["pb"] = mcap / bve if pd.notna(mcap) and bve and bve > 0 else np.nan
            st = r.get("sales_ttm", np.nan)
            r["ps"] = mcap / st if pd.notna(mcap) and st and st > 0 else np.nan
            fcf = r.get("fcf_ttm", np.nan)
            r["fcf_yield"] = fcf / mcap if pd.notna(mcap) and mcap > 0 and pd.notna(fcf) else np.nan
            payout = _g(ap, "dividend_payout_pct")
            r["div_yield"] = (payout / 100 * ni) / mcap if pd.notna(payout) and pd.notna(ni) and ni > 0 and pd.notna(mcap) and mcap > 0 else np.nan
        rows.append(r)
    out = pd.DataFrame(rows).set_index("symbol")
    if not sh.empty:
        sh["period_end"] = pd.to_datetime(sh["period_end"])
        sh = sh[sh.period_end <= pd.Timestamp(as_of)]
        prom = sh[sh.holder == "promoters"].sort_values("period_end")
        inst = sh[sh.holder.isin(["fii", "dii"])].groupby(["symbol", "period_end"]).pct.sum().reset_index().sort_values("period_end")
        out["promoter_pct"] = prom.groupby("symbol").pct.last()
        out["promoter_chg_1y"] = prom.groupby("symbol").pct.apply(lambda s: s.iloc[-1] - s.iloc[-5] if len(s) >= 5 else np.nan)
        out["inst_chg_1y"] = inst.groupby("symbol").pct.apply(lambda s: s.iloc[-1] - s.iloc[-5] if len(s) >= 5 else np.nan)
    return out.replace([np.inf, -np.inf], np.nan)


def _piotroski(ap: pd.DataFrame, is_bank: bool) -> dict:
    if len(ap) < 2:
        return {"f_score": np.nan, "f_known": np.nan}
    ta0, ta1 = _g(ap, "total_assets", -1), _g(ap, "total_assets", -2)
    ni0, ni1 = _g(ap, "net_profit", -1), _g(ap, "net_profit", -2)
    cfo0 = _g(ap, "cash_from_operating_activity", -1)
    bor0, bor1 = _g(ap, "borrowings", -1), _g(ap, "borrowings", -2)
    eq0, eq1 = _g(ap, "equity_capital", -1), _g(ap, "equity_capital", -2)
    s0, s1 = _sales(ap, -1), _sales(ap, -2)
    sig = []

    def add(ok):
        sig.append(None if ok is None else bool(ok))

    roa0 = ni0 / ta0 if ta0 and pd.notna(ni0) else None
    roa1 = ni1 / ta1 if ta1 and pd.notna(ni1) else None
    add(None if roa0 is None else roa0 > 0)
    add(None if is_bank or pd.isna(cfo0) else cfo0 > 0)
    add(None if roa0 is None or roa1 is None else roa0 > roa1)
    add(None if is_bank or pd.isna(cfo0) or pd.isna(ni0) else cfo0 > ni0)
    lev0 = bor0 / ta0 if ta0 and pd.notna(bor0) else None
    lev1 = bor1 / ta1 if ta1 and pd.notna(bor1) else None
    add(None if is_bank or lev0 is None or lev1 is None else lev0 <= lev1)
    add(None if pd.isna(eq0) or pd.isna(eq1) else eq0 <= eq1 * 1.02)
    at0 = s0 / ta0 if ta0 and pd.notna(s0) else None
    at1 = s1 / ta1 if ta1 and pd.notna(s1) else None
    add(None if at0 is None or at1 is None else at0 > at1)
    known = [s for s in sig if s is not None]
    if not known:
        return {"f_score": np.nan, "f_known": 0}
    return {"f_score": float(sum(known)), "f_known": float(len(known))}


def _altman(ap: pd.DataFrame) -> float:
    ta = _g(ap, "total_assets"); oa = _g(ap, "other_assets"); ol = _g(ap, "other_liabilities")
    re_ = _g(ap, "reserves"); op = _op(ap); dep = _g(ap, "depreciation"); oi = _g(ap, "other_income")
    eq = _g(ap, "equity_capital"); bor = _g(ap, "borrowings")
    if any(pd.isna(x) for x in (ta, oa, ol, re_, op, dep, eq, bor)) or ta <= 0:
        return np.nan
    tl = bor + ol
    if tl <= 0:
        return np.nan
    wc = oa - ol
    ebit = op - dep + (oi if pd.notna(oi) else 0)
    bve = eq + re_
    return 3.25 + 6.56 * wc / ta + 3.26 * re_ / ta + 6.72 * ebit / ta + 1.05 * bve / tl
