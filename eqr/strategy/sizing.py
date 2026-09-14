"""Inverse-volatility weights with per-name and per-industry caps, scaled by regime exposure.
Caps are hard: when they cannot all be met at full investment the remainder is cash."""
from __future__ import annotations

import numpy as np
import pandas as pd


def inverse_vol_weights(selected: list[str], vol: pd.Series, industry: pd.Series, exposure: float = 1.0,
                        cap_name: float = 0.05, cap_industry: float = 0.25, iters: int = 50) -> pd.Series:
    if not selected:
        return pd.Series(dtype=float)
    v = vol.reindex(selected).astype(float)
    v = v.fillna(v.median() if v.notna().any() else 0.3).clip(lower=0.05)
    w = 1.0 / v
    w = w / w.sum()
    ind = industry.reindex(selected).fillna("UNKNOWN")
    n = len(selected)
    cap_name = max(cap_name, 1.0 / n)                    # a cap below 1/N cannot hold
    w = w.clip(upper=cap_name)
    for _ in range(iters):
        by_ind = w.groupby(ind).sum()
        over = by_ind[by_ind > cap_industry + 1e-12]
        for i, tot in over.items():
            w[ind == i] *= cap_industry / tot
        short = 1.0 - w.sum()
        if short < 1e-9:
            break
        capped_ind = set(by_ind[by_ind >= cap_industry - 1e-9].index)
        room = (cap_name - w).clip(lower=0)
        room[ind.isin(capped_ind)] = 0.0
        if room.sum() <= 1e-12:
            break                                         # infeasible: leave the rest in cash
        w = w + room / room.sum() * min(short, room.sum())
    return (w * exposure).round(8)
