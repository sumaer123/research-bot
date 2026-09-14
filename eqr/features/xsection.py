"""Cross-sectional normalisation: MAD winsorising, z-scores within industry
(fallback: whole universe for groups under MIN_GROUP), bucket means."""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_GROUP = 8
WINSOR_MADS = 3.0

# sign: +1 higher is better, -1 lower is better; transform applied before z
BUCKETS = {
    "z_quality": [("roe", 1), ("roce", 1), ("accruals", -1), ("f_score", 1), ("debt_equity", -1),
                  ("int_cover", 1), ("opm_chg_1y", 1), ("altman_zpp", 1)],
    "z_value": [("earnings_yield", 1), ("fcf_yield", 1), ("pb", -1), ("div_yield", 1), ("ps", -1)],
    "z_momentum": [("mom_12_1", 1), ("mom_6_1", 1), ("dist_52w_high", 1), ("pat_yoy_ttm", 1), ("sales_yoy_ttm", 1)],
    "z_lowrisk": [("vol_250", -1), ("dd_250", 1), ("beta_250", -1), ("amihud_60", -1)],
}
CAPS = {"int_cover": (None, 50.0), "pb": (0.0, None), "ps": (0.0, None), "altman_zpp": (-10.0, 20.0)}


def winsorise(s: pd.Series, k: float = WINSOR_MADS) -> pd.Series:
    x = s.astype(float)
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    if not np.isfinite(mad) or mad == 0:
        return x
    return x.clip(med - k * mad, med + k * mad)


def zscore_grouped(s: pd.Series, groups: pd.Series, min_group: int = MIN_GROUP) -> pd.Series:
    """z within group where the group has >= min_group non-null values, else vs all."""
    x = winsorise(s)
    out = pd.Series(np.nan, index=s.index)
    counts = x.groupby(groups).transform(lambda g: g.notna().sum())
    big = counts >= min_group
    if big.any():
        gz = x[big].groupby(groups[big]).transform(lambda g: (g - g.mean()) / g.std(ddof=0) if g.std(ddof=0) > 0 else 0.0)
        out[big] = gz
    rest = ~big
    if rest.any():
        allz = (x - x.mean()) / x.std(ddof=0) if x.std(ddof=0) > 0 else x * 0
        out[rest] = allz[rest]
    return out.clip(-4, 4)


def bucket_scores(feat: pd.DataFrame, groups: pd.Series, min_components: int = 2) -> pd.DataFrame:
    out = pd.DataFrame(index=feat.index)
    for bucket, comps in BUCKETS.items():
        zs = []
        for col, sign in comps:
            if col not in feat.columns:
                continue
            s = feat[col].astype(float)
            lo, hi = CAPS.get(col, (None, None))
            if lo is not None or hi is not None:
                s = s.clip(lo, hi)
            if s.notna().sum() < min_components * 4:
                continue
            zs.append(sign * zscore_grouped(s, groups))
        if zs:
            z = pd.concat(zs, axis=1)
            n = z.notna().sum(axis=1)
            out[bucket] = z.mean(axis=1).where(n >= min_components)
        else:
            out[bucket] = np.nan
    out["buckets_known"] = out[list(BUCKETS)].notna().sum(axis=1)
    return out
