"""Pre-registered calibration of the rating engine (methodology plan §6.1 – §6.2).

Protocol: month-end signal dates from `start`; names = the PIT features universe; forward
12-month adjusted total return (delisted exit at last close x 0.99); benchmark = NIFTY 500 plus
a 1.3%/yr TR proxy (integrity item BENCH_PROXY); expanding yearly folds with a 12-month embargo,
variant chosen per fold on train IC among the publishable variants, holdout evaluated once;
deflated Sharpe on the long-short series with 3 + prior trials. The raw (no-hysteresis) verdicts
are judged against the bar; hysteresis statistics are reported alongside."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from ..config import settings
from ..spine.universe import month_end_sessions
from ..store import upsert
from ..store.pit import index_series
from ..validate.metrics import deflated_sharpe
from .acceptance import BAR, evaluate
from .sector import PUBLISHABLE_VARIANTS, PROFILES

log = logging.getLogger("eqr.rating.calibrate")

BUY_TIERS = ("CONVICTION_BUY", "SPECULATIVE_BUY")
SELL_TIERS = ("SELL", "TRIM")
HIST_HARD_FLAGS = ("FORENSIC_BENEISH_2Y", "FORENSIC_CASH_DIVERGENCE", "SOLVENCY_BREACH", "CAPITAL_BREACH_BANK")
TR_PROXY_ANNUAL = 0.013


@dataclass
class CalibrationConfig:
    engine_version: str = "r1"
    start: date = date(2017, 6, 30)
    end: Optional[date] = None
    holdout_start: date = date(2024, 9, 30)
    fold_years: tuple[int, ...] = (2019, 2020, 2021, 2022, 2023, 2024)
    horizon_days: int = 252
    embargo_days: int = 365
    variants: tuple[str, ...] = PUBLISHABLE_VARIANTS
    diagnostic_variants: tuple[str, ...] = ("no_valuation",)
    prior_trials: int = 0
    max_dates: Optional[int] = None            # tests / smoke runs
    progress: bool = True
    store_metrics: bool = True                 # persist each date's fund_metrics slice
    reuse_metrics: bool = True                 # load a stored slice instead of recomputing


# ----------------------------------------------------------------------------- forward returns

def forward_returns(con: duckdb.DuckDBPyConnection, as_of: date, horizon_days: int,
                    symbols: Optional[list[str]] = None) -> tuple[pd.Series, Optional[date], Optional[float]]:
    """Adjusted forward return per symbol from as_of to the session `horizon_days` later
    (delisted: last close x 0.99). Returns (series, matured_date, benchmark_return)."""
    row = con.execute("SELECT trade_date FROM trading_days WHERE trade_date > ? ORDER BY trade_date LIMIT 1 OFFSET ?",
                      [as_of, horizon_days - 1]).fetchone()
    if not row:
        return pd.Series(dtype=float), None, None
    matured = row[0]
    # anchor on the last session that actually has EQ prices (a trading_days row can lack a bhavcopy)
    px_day = con.execute("SELECT max(trade_date) FROM prices_daily WHERE trade_date <= ? AND series = 'EQ'", [matured]).fetchone()[0]
    if px_day is not None:
        matured = px_day
    where_sym = ""
    if symbols:
        where_sym = " AND symbol IN (" + ",".join("?" * len(symbols)) + ")"
    sql = f"""
        WITH p0 AS (
          SELECT symbol, close FROM prices_daily WHERE trade_date = ? AND series = 'EQ' {where_sym}
        ), p1 AS (
          SELECT symbol, close, trade_date FROM prices_daily
          WHERE trade_date <= ? AND series = 'EQ' {where_sym}
          QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY trade_date DESC) = 1
        ), f0 AS (
          SELECT p0.symbol, coalesce(exp(sum(ln(a.factor))), 1.0) AS f FROM p0
          LEFT JOIN adj_factors a ON a.symbol = p0.symbol AND a.ex_date > ? AND a.ex_date <= ?
          GROUP BY p0.symbol
        )
        SELECT p0.symbol, p0.close * f0.f AS c0, p1.close AS c1, p1.trade_date AS last_dt
        FROM p0 JOIN f0 USING (symbol) LEFT JOIN p1 USING (symbol)
    """
    # parameter order: p0.trade_date, p1 <= matured, (sym...), f0 ex_date > as_of, <= matured
    params = [as_of] + (list(symbols) if symbols else []) + [matured] + (list(symbols) if symbols else []) + [as_of, matured]
    df = con.execute(sql, params).df()
    if df.empty:
        return pd.Series(dtype=float), matured, None
    # the factor for p0 must cover ex_dates in (as_of, matured]; p1 is at/just before matured so needs no adjustment
    # unless the name delisted before matured, in which case its last close is raw and we haircut it
    grace = con.execute("SELECT min(trade_date) FROM (SELECT trade_date FROM trading_days WHERE trade_date <= ? "
                        "ORDER BY trade_date DESC LIMIT 6)", [matured]).fetchone()[0]     # 5-session grace, as the backtest
    df["delisted"] = pd.to_datetime(df["last_dt"]).dt.date < (grace or matured)
    df.loc[df.delisted, "c1"] = df.loc[df.delisted, "c1"] * (1 - 0.01)
    ret = (df["c1"] / df["c0"] - 1).where(df["c0"] > 0)
    ret.index = df["symbol"]
    b = index_series(con, "Nifty 500", start=as_of, end=matured)
    bench = None
    if len(b) > 1:
        days = (pd.Timestamp(b.trade_date.iloc[-1]) - pd.Timestamp(b.trade_date.iloc[0])).days
        bench = float(b.close.iloc[-1] / b.close.iloc[0] - 1) + TR_PROXY_ANNUAL * days / 365.0
    return ret.astype(float), matured, bench


# ----------------------------------------------------------------------------- history

def rating_history(con: duckdb.DuckDBPyConnection, cfg: CalibrationConfig,
                   variants: Optional[tuple[str, ...]] = None) -> pd.DataFrame:
    """Rate every month-end in [start, end - horizon] for every variant (no hysteresis) and
    attach forward returns. Metrics are computed once per date (stored in fund_metrics) and
    re-used across variants. Returns a long frame with one row per (as_of, variant, symbol)."""
    from .engine import rate_universe
    from ..fundamentals.base import load_inputs
    from ..fundamentals.build import build_metrics, load_metrics
    end = cfg.end or con.execute("SELECT max(as_of) FROM features").fetchone()[0]
    dates = [d for d in month_end_sessions(con, cfg.start, end)]
    feat_dates = {r[0] for r in con.execute("SELECT DISTINCT as_of FROM features").fetchall()}
    dates = [d for d in dates if d in feat_dates]
    last_ok = con.execute("SELECT trade_date FROM trading_days ORDER BY trade_date DESC LIMIT 1 OFFSET ?",
                          [cfg.horizon_days]).fetchone()
    if last_ok:
        dates = [d for d in dates if d <= last_ok[0]]
    if cfg.max_dates:
        dates = dates[-cfg.max_dates:]
    variants = variants or tuple(cfg.variants) + tuple(cfg.diagnostic_variants)
    rows = []
    t0 = time.time()
    for i, d in enumerate(dates):
        fwd, matured, bench = forward_returns(con, d, cfg.horizon_days)
        fwd36, _, bench36 = forward_returns(con, d, cfg.horizon_days * 3)
        inputs = load_inputs(con, d, with_xbrl=cfg.engine_version != "r1")
        if not inputs:
            continue
        wide = load_metrics(con, d, list(inputs)) if cfg.reuse_metrics else pd.DataFrame()
        if wide.empty or len(wide) < len(inputs) * 0.9:
            wide = build_metrics(con, d, list(inputs), store=cfg.store_metrics, with_xbrl=cfg.engine_version != "r1")
        for v in variants:
            res = rate_universe(con, d, variant=v, engine=cfg.engine_version, store=False,
                                use_hysteresis=False, inputs=inputs, wide=wide)
            for r in res:
                rows.append({
                    "as_of": d, "variant": v, "symbol": r.symbol, "profile": r.profile, "status": r.status,
                    "score": r.score, "verdict": r.decision.verdict, "rule_id": r.decision.rule_id,
                    "mos": r.valuation.mos_base, "dci": r.confidence.dci, "band": r.confidence.band,
                    "coverage": r.confidence.component_coverage,
                    "hard": ",".join(f.code for f in r.red_flags if f.tier == "HARD"),
                    "soft": ",".join(f.code for f in r.red_flags if f.tier == "SOFT"),
                    "fwd": fwd.get(r.symbol, np.nan), "bench": bench, "matured": matured,
                    "fwd36": fwd36.get(r.symbol, np.nan) if len(fwd36) else np.nan, "bench36": bench36,
                })
        if cfg.progress:
            el = time.time() - t0
            log.info("calibration %s (%d/%d) %.0fs elapsed", d, i + 1, len(dates), el)
            print(f"  [{i + 1}/{len(dates)}] {d}  {el:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["excess"] = df["fwd"] - df["bench"]
    df["excess36"] = df["fwd36"] - df["bench36"]
    return df


# ----------------------------------------------------------------------------- statistics

def nw_tstat(x: pd.Series, lag: int = 11) -> float:
    """Newey-West t-statistic of the mean of a (monthly) series."""
    x = pd.Series(x).dropna().astype(float)
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    s = float((e ** 2).sum())
    for k in range(1, min(lag, n - 1) + 1):
        w = 1 - k / (lag + 1)
        s += 2 * w * float((e.iloc[k:].values * e.iloc[:-k].values).sum())
    var_mean = s / n / n
    return float(x.mean() / np.sqrt(var_mean)) if var_mean > 0 else float("nan")


def ic_series(df: pd.DataFrame, col: str = "score", target: str = "excess") -> pd.Series:
    out = {}
    for d, g in df.groupby("as_of"):
        g = g[[col, target]].dropna()
        if len(g) >= 30:
            out[d] = float(g[col].rank().corr(g[target].rank()))
    return pd.Series(out, dtype=float)


def bucket_stats(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Mean forward excess per score decile (deciles per as_of)."""
    d = df[["as_of", "score", "excess"]].dropna().copy()
    d["decile"] = d.groupby("as_of")["score"].transform(lambda s: pd.qcut(s.rank(method="first"), n, labels=False) + 1)
    return d.groupby("decile")["excess"].agg(["mean", "count"])


def decile_monotonic(df: pd.DataFrame) -> tuple[Optional[bool], Optional[float]]:
    d = df[["as_of", "score", "excess"]].dropna().copy()
    if d.empty:
        return None, None
    d["decile"] = d.groupby("as_of")["score"].transform(lambda s: pd.qcut(s.rank(method="first"), 10, labels=False) + 1)
    overall = d.groupby("decile")["excess"].mean()
    mono_all = bool((overall.diff().dropna() > 0).all())
    years = []
    for y, g in d.groupby(pd.to_datetime(d["as_of"]).dt.year):
        m = g.groupby("decile")["excess"].mean()
        if len(m) == 10:
            years.append(bool((m.diff().dropna() > 0).all()))
    share = float(np.mean(years)) if years else None
    return mono_all, share


def tier_stats(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df.status == "RATED"][["verdict", "excess"]].dropna()
    g = d.groupby("verdict")["excess"].agg(["mean", "count"])
    g["hit"] = d.groupby("verdict")["excess"].apply(lambda s: float((s > 0).mean()))
    return g


def long_short_series(df: pd.DataFrame) -> pd.Series:
    out = {}
    for d, g in df[df.status == "RATED"].groupby("as_of"):
        g = g.dropna(subset=["excess"])
        b = g[g.verdict.isin(BUY_TIERS)]["excess"]
        s = g[g.verdict.isin(SELL_TIERS)]["excess"]
        if len(b) >= 5 and len(s) >= 5:
            out[d] = float(b.mean() - s.mean())
    return pd.Series(out, dtype=float)


def brier(train: pd.DataFrame, test: pd.DataFrame) -> tuple[Optional[float], Optional[float]]:
    """Isotonic map score -> P(excess > 0) fitted on train, scored on test; plus climatology Brier."""
    try:
        from sklearn.isotonic import IsotonicRegression
    except Exception:                                   # noqa: BLE001
        return _brier_binned(train, test)
    tr = train[["score", "excess"]].dropna(); te = test[["score", "excess"]].dropna()
    if len(tr) < 100 or len(te) < 30:
        return None, None
    y_tr = (tr.excess > 0).astype(float); y_te = (te.excess > 0).astype(float)
    iso = IsotonicRegression(out_of_bounds="clip").fit(tr.score.values, y_tr.values)
    p = iso.predict(te.score.values)
    b = float(np.mean((p - y_te.values) ** 2))
    clim = float(np.mean((y_tr.mean() - y_te.values) ** 2))
    return b, clim


def _brier_binned(train: pd.DataFrame, test: pd.DataFrame, bins: int = 10) -> tuple[Optional[float], Optional[float]]:
    tr = train[["score", "excess"]].dropna(); te = test[["score", "excess"]].dropna()
    if len(tr) < 100 or len(te) < 30:
        return None, None
    edges = np.quantile(tr.score, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    tr_bin = pd.cut(tr.score, edges, labels=False)
    rate = (tr.excess > 0).groupby(tr_bin).mean()
    rate = rate.cummax()                                   # monotone (isotonic-lite)
    te_bin = pd.cut(te.score, edges, labels=False)
    p = te_bin.map(rate).fillna(float((tr.excess > 0).mean())).values
    y = (te.excess > 0).astype(float).values
    return float(np.mean((p - y) ** 2)), float(np.mean(((tr.excess > 0).mean() - y) ** 2))


def transition_rate(df: pd.DataFrame) -> Optional[float]:
    d = df[df.status == "RATED"][["as_of", "symbol", "verdict"]].sort_values(["symbol", "as_of"])
    d["prev"] = d.groupby("symbol")["verdict"].shift()
    d = d.dropna(subset=["prev"])
    return float((d.verdict != d.prev).mean()) if len(d) else None


def hard_flag_precision(df: pd.DataFrame) -> Optional[float]:
    d = df.dropna(subset=["fwd"]).copy()
    m = d["hard"].fillna("").apply(lambda s: any(c in s.split(",") for c in HIST_HARD_FLAGS))
    d = d[m]
    if len(d) < 30:
        return None
    return float(((d.excess < 0) | d.fwd.isna()).mean())


def metrics_for(df: pd.DataFrame, holdout: Optional[pd.DataFrame] = None, n_trials: int = 3) -> dict:
    """All §6.2 statistics for one variant's frame (test-period rows)."""
    m: dict = {}
    rated = df[df.status == "RATED"]
    mono, share = decile_monotonic(rated); m["decile_monotonic_overall"], m["decile_monotonic_years_share"] = mono, share
    ts = tier_stats(rated)
    order = [t for t in ("CONVICTION_BUY", "SPECULATIVE_BUY", "HOLD", "TRIM", "SELL") if t in ts.index]
    means = [ts.loc[t, "mean"] for t in order]
    m["tiers_ordered"] = bool(all(means[i] >= means[i + 1] for i in range(len(means) - 1))) if len(means) >= 2 else None
    m["tier_stats"] = {t: {"mean_excess": float(ts.loc[t, "mean"]), "n": int(ts.loc[t, "count"]), "hit": float(ts.loc[t, "hit"])} for t in ts.index}
    ls = long_short_series(rated)
    m["long_short_pp"] = float(ls.mean()) if len(ls) else None
    m["long_short_t"] = nw_tstat(ls) if len(ls) >= 6 else None
    ic = ic_series(rated); m["ic_mean"] = float(ic.mean()) if len(ic) else None; m["ic_t"] = nw_tstat(ic) if len(ic) >= 6 else None
    ic36 = ic_series(rated.dropna(subset=["excess36"]), "mos", "excess36") if "excess36" in rated else pd.Series(dtype=float)
    m["mos_ic_mean"] = float(ic36.mean()) if len(ic36) else None; m["mos_ic_t"] = nw_tstat(ic36) if len(ic36) >= 6 else None
    m["hit_conviction_buy"] = m["tier_stats"].get("CONVICTION_BUY", {}).get("hit")
    buy = rated[rated.verdict.isin(BUY_TIERS)].dropna(subset=["excess"])
    m["hit_all_buy"] = float((buy.excess > 0).mean()) if len(buy) >= 20 else None
    sell = rated[rated.verdict == "SELL"].dropna(subset=["excess"])
    m["hit_sell"] = float((sell.excess < 0).mean()) if len(sell) >= 20 else None
    m["hard_flag_precision"] = hard_flag_precision(df)
    if holdout is not None and len(holdout):
        b, clim = brier(rated, holdout[holdout.status == "RATED"])
    else:
        yrs = sorted(pd.to_datetime(rated.as_of).dt.year.unique())
        if len(yrs) >= 3:
            cut = yrs[-1]
            b, clim = brier(rated[pd.to_datetime(rated.as_of).dt.year < cut], rated[pd.to_datetime(rated.as_of).dt.year == cut])
        else:
            b, clim = None, None
    m["brier"] = b; m["brier_gain_vs_climatology"] = (clim - b) if b is not None and clim is not None else None
    cc = rated[["score", "coverage"]].dropna()
    m["score_coverage_corr"] = float(cc.score.corr(cc.coverage)) if len(cc) > 50 else None
    hi = ic_series(rated[rated.band == "HIGH"]); lo = ic_series(rated[rated.band == "LOW"])
    m["ic_high_dci"] = float(hi.mean()) if len(hi) else None; m["ic_low_dci"] = float(lo.mean()) if len(lo) else None
    m["dci_informative"] = (m["ic_high_dci"] >= m["ic_low_dci"]) if (m["ic_high_dci"] is not None and m["ic_low_dci"] is not None) else None
    conv = rated[rated.verdict == "CONVICTION_BUY"]
    if len(conv) >= 20:
        share_by = conv.groupby("as_of")["profile"].value_counts(normalize=True).groupby("profile").mean()
        m["sector_max_share_conviction"] = float(share_by.max())
    else:
        m["sector_max_share_conviction"] = None
    pos = 0
    for p in PROFILES:
        lsp = long_short_series(rated[rated.profile == p])
        if len(lsp) and lsp.mean() > 0:
            pos += 1
    m["sector_ls_positive_profiles"] = pos
    m["monthly_transition"] = transition_rate(rated)
    shares = rated.groupby("as_of")["verdict"].value_counts(normalize=True).groupby("verdict").mean()
    m["tier_shares"] = {k: float(v) for k, v in shares.items()}
    m["min_tier_share"] = float(shares.reindex(["CONVICTION_BUY", "SPECULATIVE_BUY", "HOLD", "TRIM", "SELL"]).fillna(0).min())
    if len(ls) >= 30:
        ds = deflated_sharpe(ls / 12.0, n_trials=n_trials, rf_annual=0.0)   # monthly long-short as a return series
        m["dsr_p"] = float(ds.get("p_value")) if ds.get("p_value") == ds.get("p_value") else None
    else:
        m["dsr_p"] = None
    if holdout is not None and len(holdout):
        hls = long_short_series(holdout[holdout.status == "RATED"])
        m["holdout_long_short"] = float(hls.mean()) if len(hls) else None
        hts = tier_stats(holdout[holdout.status == "RATED"])
        m["holdout_tier_stats"] = {t: {"mean_excess": float(hts.loc[t, "mean"]), "n": int(hts.loc[t, "count"])} for t in hts.index}
    else:
        m["holdout_long_short"] = None
    m["n_obs"] = int(len(rated)); m["n_dates"] = int(rated.as_of.nunique())
    return m


# ----------------------------------------------------------------------------- protocol

def run_calibration(con: duckdb.DuckDBPyConnection, cfg: CalibrationConfig, hist: Optional[pd.DataFrame] = None,
                    store: bool = True) -> dict:
    """The pre-registered protocol. `hist` may be passed (tests) instead of being rated here."""
    t0 = time.time()
    df = hist if hist is not None else rating_history(con, cfg)
    if df.empty:
        return {"verdict": "NOT VALIDATED", "reason": "no history", "engine_version": cfg.engine_version}
    df["year"] = pd.to_datetime(df["as_of"]).dt.year
    pre = df[df.as_of < cfg.holdout_start]
    hold = df[df.as_of >= cfg.holdout_start]
    folds = []
    test_rows = {v: [] for v in cfg.variants}
    for y in cfg.fold_years:
        test_start = date(y, 1, 1)
        train_end = date(y - 1, 12, 31)
        tr = pre[(pre.as_of <= train_end) & (pd.to_datetime(pre.matured).dt.date <= test_start)]   # embargo: matured before test
        te = pre[pre.year == y]
        if te.empty or tr.empty:
            continue
        ics = {v: float(ic_series(tr[tr.variant == v]).mean() or 0.0) for v in cfg.variants}
        best = max(ics, key=ics.get)
        folds.append({"year": y, "selected": best, "train_ic": ics, "n_train": int(len(tr)), "n_test": int(len(te))})
        test_rows[best].append(te[te.variant == best])
    # OOS = concatenation of each fold's test rows under its selected variant
    oos = pd.concat([pd.concat(v) for v in test_rows.values() if v]) if any(test_rows.values()) else pd.DataFrame()
    # holdout: select on everything before the holdout, evaluate once
    pre_h = pre[pd.to_datetime(pre.matured).dt.date <= cfg.holdout_start]
    ics_h = {v: float(ic_series(pre_h[pre_h.variant == v]).mean() or 0.0) for v in cfg.variants} if len(pre_h) else {}
    sel_h = max(ics_h, key=ics_h.get) if ics_h else cfg.variants[0]
    hold_sel = hold[hold.variant == sel_h]
    n_trials = len(cfg.variants) + cfg.prior_trials
    m = metrics_for(oos, holdout=hold_sel, n_trials=n_trials) if len(oos) else {}
    acc = evaluate(m) if m else {"verdict": "NOT VALIDATED"}
    # per-variant full-period diagnostics (incl. the no_valuation double-count check)
    diag = {}
    for v in list(cfg.variants) + list(cfg.diagnostic_variants):
        sub = pre[pre.variant == v]
        if len(sub):
            icv = ic_series(sub)
            diag[v] = {"ic_mean": float(icv.mean()) if len(icv) else None, "ic_se": float(icv.std() / np.sqrt(len(icv))) if len(icv) > 1 else None,
                       "long_short_pp": float(long_short_series(sub).mean()) if len(long_short_series(sub)) else None}
    hyst_note = "raw (no-hysteresis) verdicts judged; hysteresis is applied only in the live nightly publish"
    run_id = f"calibrate-{cfg.engine_version}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out = {
        "run_id": run_id, "engine_version": cfg.engine_version, "start": str(cfg.start), "end": str(cfg.end),
        "holdout_start": str(cfg.holdout_start), "folds": folds, "holdout_selected": sel_h, "holdout_train_ic": ics_h,
        "n_trials": n_trials, "metrics": m, "acceptance": acc, "verdict": acc.get("verdict", "NOT VALIDATED"),
        "variant_diagnostics": diag, "bar": BAR, "note": hyst_note, "elapsed_s": round(time.time() - t0, 1),
        "n_history_rows": int(len(df)),
    }
    if store:
        from .report import write_calibration_report
        path = write_calibration_report(out, df)
        out["report_path"] = str(path)
        con.execute("INSERT OR REPLACE INTO rating_calibrations (run_id, engine_version, start_date, end_date, holdout_start, "
                    "n_obs, metrics_json, acceptance_json, verdict, report_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [run_id, cfg.engine_version, cfg.start, cfg.end, cfg.holdout_start, int(m.get("n_obs", 0)),
                     json.dumps(m, default=str), json.dumps(acc, default=str), out["verdict"], str(path), datetime.now()])
        try:
            from ..validate import trials
            key = f"RATING-{cfg.engine_version}"
            trials.append_trial({"ts": datetime.now().isoformat(timespec="seconds"), "sleeve": key, "purpose": "protocol",
                                 "run_id": run_id, "grid": [f"{cfg.engine_version}-{v}" for v in cfg.variants],
                                 "n_grid": len(cfg.variants), "holdout_start": str(cfg.holdout_start),
                                 "start": str(cfg.start), "end": str(cfg.end), "code_commit": trials.code_commit(),
                                 "report_path": str(path), "report_sha256": trials._sha256(path)}, key)
        except Exception as e:                       # noqa: BLE001 - never block on the ledger
            log.warning("trial ledger append skipped: %s", e)
    return out
