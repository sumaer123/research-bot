"""Performance statistics on daily return series, incl. deflated Sharpe
(Bailey & Lopez de Prado 2014) for multiple-trial honesty."""
from __future__ import annotations

from math import sqrt, exp

import numpy as np
import pandas as pd
from scipy import stats

ANN = 252
EULER = 0.5772156649


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return float("nan")
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) if years > 0 else float("nan")


def max_drawdown(equity: pd.Series) -> float:
    dd = equity / equity.cummax() - 1
    return float(dd.min())


def sharpe(returns: pd.Series, rf_annual: float = 0.06) -> float:
    r = returns.dropna() - rf_annual / ANN
    return float(r.mean() / r.std(ddof=1) * sqrt(ANN)) if len(r) > 2 and r.std(ddof=1) > 0 else float("nan")


def sortino(returns: pd.Series, rf_annual: float = 0.06) -> float:
    r = returns.dropna() - rf_annual / ANN
    dn = r[r < 0].std(ddof=1)
    return float(r.mean() / dn * sqrt(ANN)) if len(r) > 2 and dn and dn > 0 else float("nan")


def information_ratio(returns: pd.Series, bench: pd.Series) -> tuple[float, float]:
    a = (returns - bench.reindex(returns.index)).dropna()
    te = a.std(ddof=1) * sqrt(ANN)
    ir = a.mean() * ANN / te if te and te > 0 else float("nan")
    return float(ir), float(te)


def probabilistic_sharpe(sr_per_period: float, sr0_per_period: float, n: int, skew: float, kurt: float) -> float:
    """PSR: probability that the true SR exceeds sr0, given non-normal returns (kurt is
    the full (Pearson) kurtosis, 3 for normal)."""
    if n < 3:
        return float("nan")
    denom = sqrt(max(1e-12, 1 - skew * sr_per_period + (kurt - 1) / 4 * sr_per_period ** 2))
    z = (sr_per_period - sr0_per_period) * sqrt(n - 1) / denom
    return float(stats.norm.cdf(z))


def deflated_sharpe(returns: pd.Series, n_trials: int, trial_sr_var: float | None = None,
                    rf_annual: float = 0.06) -> dict:
    """Deflated Sharpe ratio: PSR against the expected maximum SR of `n_trials`
    independent trials. trial_sr_var = variance of the per-period SRs across trials
    (defaults to the observed per-period SR^2 / 4, a conservative stand-in when
    the trial set is small)."""
    r = (returns.dropna() - rf_annual / ANN)
    n = len(r)
    if n < 30 or r.std(ddof=1) == 0:
        return {"dsr": float("nan"), "p_value": float("nan"), "sr0_annual": float("nan"), "n": n}
    sr = r.mean() / r.std(ddof=1)
    if trial_sr_var is None or not np.isfinite(trial_sr_var) or trial_sr_var <= 0:
        trial_sr_var = (sr ** 2) / 4 if sr != 0 else 1e-6
    n_trials = max(1, int(n_trials))
    if n_trials == 1:
        sr0 = 0.0
    else:
        sr0 = sqrt(trial_sr_var) * ((1 - EULER) * stats.norm.ppf(1 - 1 / n_trials)
                                    + EULER * stats.norm.ppf(1 - 1 / (n_trials * exp(1))))
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))
    dsr = probabilistic_sharpe(sr, sr0, n, skew, kurt)
    return {"dsr": dsr, "p_value": 1 - dsr, "sr_annual": float(sr * sqrt(ANN)), "sr0_annual": float(sr0 * sqrt(ANN)),
            "skew": skew, "kurtosis": kurt, "n": n, "n_trials": n_trials}


def summarize(equity: pd.Series, bench_equity: pd.Series | None = None, rf_annual: float = 0.06,
              turnover_annual: float | None = None, costs_bps_annual: float | None = None) -> dict:
    r = equity.pct_change().dropna()
    out = {
        "start": str(equity.index[0].date()), "end": str(equity.index[-1].date()), "days": int(len(equity)),
        "cagr": cagr(equity), "vol": float(r.std(ddof=1) * sqrt(ANN)), "sharpe": sharpe(r, rf_annual),
        "sortino": sortino(r, rf_annual), "max_drawdown": max_drawdown(equity),
        "calmar": float(cagr(equity) / abs(max_drawdown(equity))) if max_drawdown(equity) < 0 else float("nan"),
        "best_month": float(equity.resample("ME").last().pct_change().max()),
        "worst_month": float(equity.resample("ME").last().pct_change().min()),
        "hit_rate_monthly": float((equity.resample("ME").last().pct_change().dropna() > 0).mean()),
        "final_multiple": float(equity.iloc[-1] / equity.iloc[0]),
    }
    if bench_equity is not None and len(bench_equity) > 2:
        b = bench_equity.reindex(equity.index).ffill()
        br = b.pct_change().dropna()
        ir, te = information_ratio(r, br)
        out.update({"bench_cagr": cagr(b), "bench_max_drawdown": max_drawdown(b), "bench_sharpe": sharpe(br, rf_annual),
                    "excess_cagr": out["cagr"] - cagr(b), "information_ratio": ir, "tracking_error": te,
                    "beta": float(r.cov(br) / br.var()) if br.var() > 0 else float("nan")})
    if turnover_annual is not None:
        out["turnover_annual"] = turnover_annual
    if costs_bps_annual is not None:
        out["costs_bps_annual"] = costs_bps_annual
    return out
