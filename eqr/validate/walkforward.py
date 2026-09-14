"""Walk-forward over yearly folds with an embargo, a tiny pre-registered trial grid,
deflated Sharpe over the OOS path, one untouched holdout, robustness variants."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

import duckdb
import numpy as np
import pandas as pd

from ..config import settings
from ..features.panel import load_panel, window_start
from ..strategy.regime import regime_table
from ..strategy.sleeves import SleeveConfig
from .acceptance import evaluate
from .backtest import BacktestConfig, BacktestResult, run_backtest, _bench
from .costs import CostModel, DISCOUNT_BROKER
from .metrics import sharpe, deflated_sharpe, summarize, ANN


def default_grid(sleeve: str) -> list[SleeveConfig]:
    mk = SleeveConfig.L if sleeve == "L" else SleeveConfig.S
    return [mk(top_n=n, variant=v) for n in (20, 30) for v in ("base", "quality_tilt", "momentum_tilt")] \
        if sleeve == "L" else [mk(top_n=n, variant=v) for n in (20, 30) for v in ("base", "breakout_tilt", "flow_tilt")]


@dataclass
class WalkForwardConfig:
    sleeve: str
    start: date
    end: date
    holdout_start: date
    fold_years: list[int]
    capital: float = 1_000_000.0
    costs: CostModel = DISCOUNT_BROKER
    grid: list[SleeveConfig] = field(default_factory=list)
    embargo_days: int = 30
    purge_sessions: Optional[int] = None
    robustness_turnover: tuple[float, ...] = (3e7,)
    prior_trials: int = 0                         # distinct configs tried in earlier runs (trial ledger)
    rf_annual: float = field(default_factory=lambda: settings().risk_free_pct / 100)

    def __post_init__(self):
        if not self.grid:
            self.grid = default_grid(self.sleeve)
        if self.purge_sessions is None:
            self.purge_sessions = 21 if self.sleeve == "L" else 5


def _key(cfg: SleeveConfig) -> str:
    return f"{cfg.name}-N{cfg.top_n}-{cfg.variant}-T{int(cfg.min_turnover_inr / 1e7)}cr"


def _equity(r: pd.Series) -> pd.Series:
    return (1 + r).cumprod()


def run_walk_forward(con: duckdb.DuckDBPyConnection, wf: WalkForwardConfig,
                     progress: Optional[Callable[[str], None]] = None) -> dict:
    panel = load_panel(con, window_start(wf.start, 420), wf.end, series=("EQ", "BE", "BZ"))
    reg = regime_table(con, end=wf.end)
    feature_cache: dict = {}
    results: dict[str, BacktestResult] = {}
    for cfg in wf.grid:
        k = _key(cfg)
        if progress:
            progress(f"trial {k}")
        results[k] = run_backtest(con, BacktestConfig(sleeve=cfg, start=wf.start, end=wf.end, capital=wf.capital,
                                                      costs=wf.costs, rf_annual=wf.rf_annual),
                                  panel=panel, reg=reg, feature_cache=feature_cache)
    daily = {k: r.daily_returns for k, r in results.items()}
    bench_eq = _bench(con, wf.start, wf.end)
    bench_r = bench_eq.pct_change().dropna()

    folds = []
    oos_parts, oos_bench_parts = [], []
    for y in wf.fold_years:
        test_start, test_end = date(y, 1, 1), date(y, 12, 31)
        if test_start >= wf.holdout_start:
            break
        train_end = test_start - timedelta(days=wf.embargo_days)
        train_sr = {k: sharpe(r[str(wf.start):str(train_end)], wf.rf_annual) for k, r in daily.items()}
        train_sr = {k: v for k, v in train_sr.items() if np.isfinite(v)}
        if not train_sr or len(daily[next(iter(train_sr))][str(wf.start):str(train_end)]) < 250:
            continue
        best = max(train_sr, key=train_sr.get)
        seg = daily[best][str(test_start):str(min(test_end, wf.holdout_start - timedelta(days=1)))]
        seg = seg.iloc[wf.purge_sessions:]                   # purge the overlap with the training boundary
        if len(seg) < 40:
            continue
        b = bench_r.reindex(seg.index).fillna(0)
        eq, beq = _equity(seg), _equity(b)
        s = summarize(eq * 100, beq * 100, wf.rf_annual)
        folds.append({"year": y, "selected": best, "train_sharpe": round(train_sr[best], 3),
                      "test_days": int(len(seg)), "test_sharpe": round(s["sharpe"], 3),
                      "test_cagr": round(s["cagr"], 4), "test_bench_cagr": round(s["bench_cagr"], 4),
                      "test_excess_cagr": round(s["excess_cagr"], 4), "test_max_drawdown": round(s["max_drawdown"], 4)})
        oos_parts.append(seg); oos_bench_parts.append(b)
    oos = pd.concat(oos_parts) if oos_parts else pd.Series(dtype=float)
    oos_b = pd.concat(oos_bench_parts) if oos_bench_parts else pd.Series(dtype=float)
    oos_metrics = summarize(_equity(oos) * 100, _equity(oos_b) * 100, wf.rf_annual) if len(oos) > 50 else {}

    # deflated Sharpe: trial variance = variance of per-period SRs across the grid on the OOS dates
    trial_srs = []
    for k, r in daily.items():
        rr = r.reindex(oos.index).dropna() - wf.rf_annual / ANN
        if len(rr) > 30 and rr.std(ddof=1) > 0:
            trial_srs.append(rr.mean() / rr.std(ddof=1))
    trial_var = float(np.var(trial_srs, ddof=1)) if len(trial_srs) > 1 else None
    n_trials = len(wf.grid) + wf.prior_trials
    dsr = deflated_sharpe(oos, n_trials=n_trials, trial_sr_var=trial_var, rf_annual=wf.rf_annual) if len(oos) > 50 else {}

    # holdout: config chosen on everything before the holdout (with embargo), evaluated once
    ho_train_end = wf.holdout_start - timedelta(days=wf.embargo_days)
    ho_sr = {k: sharpe(r[str(wf.start):str(ho_train_end)], wf.rf_annual) for k, r in daily.items()}
    ho_best = max(ho_sr, key=ho_sr.get)
    ho = daily[ho_best][str(wf.holdout_start):str(wf.end)].iloc[wf.purge_sessions:]
    ho_b = bench_r.reindex(ho.index).fillna(0)
    holdout = {"selected": ho_best, **({k: (round(v, 4) if isinstance(v, float) else v)
                                        for k, v in summarize(_equity(ho) * 100, _equity(ho_b) * 100, wf.rf_annual).items()}
                                       if len(ho) > 40 else {})}

    # robustness: the holdout-selected config across N and universe thresholds, full period OOS-style summary
    robustness = []
    sel_cfg = next(c for c in wf.grid if _key(c) == ho_best)
    variants = []
    for n in (20, 30):
        for t in dict.fromkeys((sel_cfg.min_turnover_inr, *wf.robustness_turnover)):      # unique floors
            c = SleeveConfig.L(top_n=n, variant=sel_cfg.variant) if wf.sleeve == "L" else SleeveConfig.S(top_n=n, variant=sel_cfg.variant)
            c.min_turnover_inr = t
            variants.append(c)
    for c in variants:
        k = _key(c)
        if k in results:
            r = results[k]
        else:
            if progress:
                progress(f"robustness {k}")
            r = run_backtest(con, BacktestConfig(sleeve=c, start=wf.start, end=wf.end, capital=wf.capital,
                                                 costs=wf.costs, rf_annual=wf.rf_annual),
                             panel=panel, reg=reg, feature_cache=feature_cache)
            results[k] = r
        seg = r.daily_returns[str(wf.fold_years[0]):str(wf.holdout_start - timedelta(days=1))]
        s = summarize(_equity(seg) * 100, _equity(bench_r.reindex(seg.index).fillna(0)) * 100, wf.rf_annual)
        robustness.append({"variant": k, "sharpe": round(s["sharpe"], 3), "cagr": round(s["cagr"], 4),
                           "excess_cagr": round(s["excess_cagr"], 4), "max_drawdown": round(s["max_drawdown"], 4)})

    sel = results[ho_best]
    capacity = {"median_participation": sel.stats.get("median_participation"),
                "p90_participation": sel.stats.get("p90_participation"),
                "turnover_annual": sel.stats.get("turnover_annual"), "costs_bps_annual": sel.stats.get("costs_bps_annual")}
    acceptance = evaluate(oos_metrics, folds, dsr, robustness, capacity)
    per_config = {k: {kk: (round(v, 4) if isinstance(v, float) else v) for kk, v in r.stats.items()
                      if kk in ("cagr", "sharpe", "max_drawdown", "information_ratio", "turnover_annual",
                                "costs_bps_annual", "excess_cagr", "final_equity")} for k, r in results.items()}
    return {"sleeve": wf.sleeve, "start": str(wf.start), "end": str(wf.end), "holdout_start": str(wf.holdout_start),
            "capital": wf.capital, "costs": wf.costs.to_dict(), "rf_annual": wf.rf_annual, "grid": [_key(c) for c in wf.grid],
            "prior_trials": wf.prior_trials, "embargo_days": wf.embargo_days, "purge_sessions": wf.purge_sessions,
            "folds": folds, "oos": oos_metrics, "dsr": dsr, "holdout": holdout, "robustness": robustness,
            "capacity": capacity, "acceptance": acceptance, "per_config": per_config,
            "_results": results, "_oos": oos, "_oos_bench": oos_b}
