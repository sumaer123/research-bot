from datetime import date

import numpy as np
import pandas as pd

from eqr.strategy.sleeves import SleeveConfig, score_L, select, eligible
from eqr.strategy.sizing import inverse_vol_weights
from eqr.strategy.regime import regime_table, regime_at
from tests.conftest import make_synthetic_market


def _feat(n=50):
    rng = np.random.default_rng(1)
    idx = [f"S{i:02d}" for i in range(n)]
    f = pd.DataFrame({"z_quality": rng.normal(size=n), "z_value": rng.normal(size=n),
                      "z_momentum": rng.normal(size=n), "z_lowrisk": rng.normal(size=n),
                      "rankable": 1, "in_fo_ban": 0, "turnover_med120": 5e7, "close": 100.0,
                      "history_days": 300, "pat_ttm": 10.0, "vol_60": rng.uniform(0.2, 0.6, n),
                      "industry": [f"I{i % 4}" for i in range(n)]}, index=idx)
    return f


def test_score_L_renormalises_missing_bucket():
    f = _feat(10)
    cfg = SleeveConfig.L()
    f.loc["S00", "z_value"] = np.nan
    s = score_L(f, cfg)
    assert pd.notna(s["S00"])
    f.loc["S01", ["z_value", "z_quality", "z_momentum"]] = np.nan
    assert pd.isna(score_L(f, cfg)["S01"])          # fewer than 2 buckets -> not scored


def test_select_hysteresis_and_gate():
    f = _feat(60)
    cfg = SleeveConfig.L(top_n=10)
    s = score_L(f, cfg)
    first = select(s, [], cfg)
    assert len(first) == 10
    order = s.sort_values(ascending=False).index.tolist()
    held = order[12]                                   # rank 13 <= hold_until_rank 15 -> kept
    chosen = select(s, [held], cfg)
    assert held in chosen and len(chosen) == 10
    dropped = order[30]
    assert dropped not in select(s, [dropped], cfg)
    assert select(s, [held], cfg, allow_new=False) == [held]


def test_eligibility_filters():
    f = _feat(5)
    cfg = SleeveConfig.L()
    f.loc["S00", "pat_ttm"] = -1
    f.loc["S01", "turnover_med120"] = 1e5
    f.loc["S02", "in_fo_ban"] = 1
    e = eligible(f, cfg)
    assert not e["S00"] and not e["S01"] and not e["S02"] and e["S03"]


def test_sizing_caps():
    f = _feat(30)
    w = inverse_vol_weights(list(f.index), f["vol_60"], f["industry"], exposure=1.0, cap_name=0.05, cap_industry=0.25)
    assert abs(w.sum() - 1.0) < 1e-5 and w.max() <= 0.05 + 1e-9
    assert w.groupby(f["industry"]).sum().max() <= 0.25 + 0.02
    w2 = inverse_vol_weights(list(f.index[:5]), f["vol_60"], f["industry"], exposure=0.7, cap_name=0.05)
    assert w2.sum() <= 0.7 + 1e-9 and w2.max() <= 0.2 * 0.7 + 1e-9   # cap lifts to 1/N; infeasible caps leave cash


def test_regime(tmp_db):
    syms, days = make_synthetic_market(tmp_db, n_symbols=3, n_days=600)
    reg = regime_table(tmp_db)
    assert set(reg.regime.unique()) <= {"RISK_ON", "NEUTRAL", "RISK_OFF"}
    r, e = regime_at(reg, days[-1].date())
    assert e in (1.0, 0.7, 0.4)
