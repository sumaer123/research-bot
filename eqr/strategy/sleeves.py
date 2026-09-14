"""Two sleeves with fixed, few weights. Scores are cross-sectional composites;
selection uses rank hysteresis so a holding is not churned by a one-rank move."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from ..features.xsection import zscore_grouped

L_WEIGHT_VARIANTS = {
    "base": {"z_quality": 0.30, "z_value": 0.25, "z_momentum": 0.30, "z_lowrisk": 0.15},
    "quality_tilt": {"z_quality": 0.40, "z_value": 0.20, "z_momentum": 0.25, "z_lowrisk": 0.15},
    "momentum_tilt": {"z_quality": 0.25, "z_value": 0.20, "z_momentum": 0.40, "z_lowrisk": 0.15},
}
S_WEIGHT_VARIANTS = {
    "base": {"mom_1": 0.40, "breakout": 0.30, "deliv": 0.30},
    "breakout_tilt": {"mom_1": 0.30, "breakout": 0.45, "deliv": 0.25},
    "flow_tilt": {"mom_1": 0.30, "breakout": 0.25, "deliv": 0.45},
}


@dataclass
class SleeveConfig:
    name: str                                   # "L" | "S"
    top_n: int = 30
    hold_until_rank: int = 45
    weights: dict = field(default_factory=lambda: dict(L_WEIGHT_VARIANTS["base"]))
    variant: str = "base"
    rebalance: str = "M"                        # "M" monthly | "W" weekly
    min_turnover_inr: float = 1e7
    min_price: float = 20.0
    stop_loss: Optional[float] = None
    require_positive_pat: bool = True
    regime_gate: bool = False                   # S: no new entries when RISK_OFF
    cap_name: float = 0.05
    cap_industry: float = 0.25
    min_hold_sessions: int = 0                  # a new position cannot be rotated out before this (stops still fire)

    @staticmethod
    def L(top_n: int = 30, variant: str = "base") -> "SleeveConfig":
        return SleeveConfig(name="L", top_n=top_n, hold_until_rank=int(top_n * 1.5),
                            weights=dict(L_WEIGHT_VARIANTS[variant]), variant=variant, rebalance="M",
                            min_turnover_inr=1e7, require_positive_pat=True)

    @staticmethod
    def S(top_n: int = 20, variant: str = "base") -> "SleeveConfig":
        return SleeveConfig(name="S", top_n=top_n, hold_until_rank=int(top_n * 1.5),
                            weights=dict(S_WEIGHT_VARIANTS[variant]), variant=variant, rebalance="W",
                            min_turnover_inr=3e7, stop_loss=0.08, require_positive_pat=False,
                            regime_gate=True, cap_name=0.08, cap_industry=0.30)


def eligible(feat: pd.DataFrame, cfg: SleeveConfig) -> pd.Series:
    ok = (feat["rankable"] == 1) & (feat["in_fo_ban"] == 0)
    ok &= feat["turnover_med120"].fillna(0) >= cfg.min_turnover_inr
    ok &= feat["close"].fillna(0) >= cfg.min_price
    ok &= feat["history_days"].fillna(0) >= 250
    if cfg.require_positive_pat:
        ok &= feat["pat_ttm"].fillna(-1) > 0
    return ok


def score_L(feat: pd.DataFrame, cfg: SleeveConfig) -> pd.Series:
    cols = list(cfg.weights)
    z = feat[cols].astype(float)
    w = pd.Series(cfg.weights)
    known = z.notna()
    # renormalise weights over known buckets so a missing bucket is neither 0 nor a penalty
    num = (z.fillna(0) * w).sum(axis=1)
    den = (known * w).sum(axis=1)
    s = num / den.where(den > 0)
    s[known.sum(axis=1) < 2] = np.nan
    return s


def score_S(feat: pd.DataFrame, cfg: SleeveConfig) -> pd.Series:
    g = feat["industry"].fillna("UNKNOWN")
    z_mom = zscore_grouped(feat["mom_1"].astype(float), g)
    near_high = (feat["dist_52w_high"].astype(float) >= -0.05)
    vol_surge = feat["vol_ratio_20_120"].astype(float).clip(0, 5)
    breakout = zscore_grouped(vol_surge.where(near_high, 0.0), g)
    z_del = zscore_grouped(feat["deliv_ratio"].astype(float).clip(0, 5), g)
    w = cfg.weights
    s = w["mom_1"] * z_mom + w["breakout"] * breakout + w["deliv"] * z_del
    s[feat["mom_1"].isna()] = np.nan
    return s


def score(feat: pd.DataFrame, cfg: SleeveConfig) -> pd.Series:
    s = score_L(feat, cfg) if cfg.name == "L" else score_S(feat, cfg)
    return s.where(eligible(feat, cfg))


def select(scores: pd.Series, prev: list[str], cfg: SleeveConfig, allow_new: bool = True,
           locked: Optional[set] = None) -> list[str]:
    """Top-N with hysteresis: keep previous holdings still ranked <= hold_until_rank (and
    every `locked` holding inside its minimum hold), fill the remainder with the best new
    names (unless allow_new is False)."""
    s = scores.dropna().sort_values(ascending=False)
    rank = pd.Series(np.arange(1, len(s) + 1), index=s.index)
    locked = locked or set()
    keep = [p for p in prev if p in locked] + \
           [p for p in prev if p not in locked and p in rank.index and rank[p] <= cfg.hold_until_rank]
    if not allow_new:
        return keep[:cfg.top_n]
    out = list(keep)
    for sym in s.index:
        if len(out) >= cfg.top_n:
            break
        if sym not in out:
            out.append(sym)
    return out


def rank_table(scores: pd.Series) -> pd.DataFrame:
    s = scores.dropna().sort_values(ascending=False)
    return pd.DataFrame({"symbol": s.index, "score": s.values, "rank": np.arange(1, len(s) + 1)})
