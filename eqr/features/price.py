"""Rolling price/volume features sampled at an as-of position of a PricePanel.
Everything uses rows <= pos; NaN means UNKNOWN."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .panel import PricePanel


def _ret_window(close: pd.DataFrame, pos: int, n: int) -> pd.DataFrame:
    lo = max(0, pos - n)
    return np.log(close.iloc[lo:pos + 1]).diff().iloc[1:]


def price_features(panel: PricePanel, pos: int, bench_close: pd.Series | None = None) -> pd.DataFrame:
    c = panel.close
    t = c.iloc[pos]
    n = pos + 1

    def back(k):
        return c.iloc[pos - k] if pos - k >= 0 else pd.Series(np.nan, index=c.columns)

    out = pd.DataFrame(index=c.columns)
    out["close"] = panel.raw_close.iloc[pos]
    out["history_days"] = c.iloc[:n].notna().sum()
    out["mom_12_1"] = back(21) / back(252) - 1
    out["mom_6_1"] = back(21) / back(126) - 1
    out["mom_1"] = t / back(21) - 1
    r60, r250 = _ret_window(c, pos, 60), _ret_window(c, pos, 250)
    out["vol_60"] = r60.std() * np.sqrt(252)
    out["vol_250"] = r250.std() * np.sqrt(252)
    w250 = c.iloc[max(0, pos - 250):n]
    out["dist_52w_high"] = t / w250.max() - 1
    out["dd_250"] = (w250 / w250.cummax() - 1).min()
    out["dma50_ratio"] = t / c.iloc[max(0, pos - 49):n].mean() - 1
    out["dma200_ratio"] = t / c.iloc[max(0, pos - 199):n].mean() - 1
    h, l, pc = panel.high.iloc[max(0, pos - 13):n], panel.low.iloc[max(0, pos - 13):n], panel.prev_close.iloc[max(0, pos - 13):n]
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()]).groupby(level=0).max()
    out["atr14_pct"] = tr.mean() / t
    to = panel.turnover
    out["adv20_inr"] = to.iloc[max(0, pos - 19):n].mean()
    out["turnover_med120"] = to.iloc[max(0, pos - 119):n].median()
    v = panel.volume
    out["vol_ratio_20_120"] = v.iloc[max(0, pos - 19):n].mean() / v.iloc[max(0, pos - 119):n].mean()
    dp = panel.deliv_pct
    out["deliv_pct_20"] = dp.iloc[max(0, pos - 19):n].mean()
    out["deliv_ratio"] = out["deliv_pct_20"] / dp.iloc[max(0, pos - 119):n].mean()
    ab = _ret_window(c, pos, 60).abs()
    out["amihud_60"] = (ab / to.iloc[max(0, pos - 59):n].iloc[-len(ab):].values).mean() * 1e9
    if bench_close is not None and len(bench_close) > 30:
        b = np.log(bench_close.reindex(c.index).ffill()).diff().iloc[max(1, pos - 250 + 1):n]
        rr = np.log(c).diff().iloc[max(1, pos - 250 + 1):n]
        b = b.reindex(rr.index)
        bv = b.var()
        cov = rr.apply(lambda col: col.cov(b))
        beta = cov / bv if bv and bv > 0 else pd.Series(np.nan, index=c.columns)
        resid = rr - np.outer(b.fillna(0), beta.fillna(0))
        out["beta_250"] = beta
        out["idio_vol_250"] = resid.std() * np.sqrt(252)
    else:
        out["beta_250"] = np.nan
        out["idio_vol_250"] = np.nan
    out.index.name = "symbol"
    return out.replace([np.inf, -np.inf], np.nan)
