from datetime import date

import numpy as np

from eqr.spine.adjust import refresh_factors, detect_factors
from eqr.spine.universe import build_universe
from eqr.features.build import build_features
from eqr.features.panel import load_panel
from eqr.features.xsection import zscore_grouped, winsorise
from eqr.store import query
from tests.conftest import make_synthetic_market
import pandas as pd


def test_split_factor_detected_and_panel_adjusted(tmp_db):
    syms, days = make_synthetic_market(tmp_db, n_symbols=5, n_days=400)
    f = detect_factors(tmp_db)
    assert len(f) == 1 and f.iloc[0].symbol == "S01" and abs(f.iloc[0].factor - 0.5) < 1e-6
    assert "bonus 1:1" in f.iloc[0].kind
    refresh_factors(tmp_db)
    panel = load_panel(tmp_db, days[0].date(), days[-1].date())
    c = panel.close["S01"]
    raw = panel.raw_close["S01"]
    # pre-split adjusted = raw * 0.5 ; post-split unchanged ; no jump at the split
    assert abs(c.iloc[100] / raw.iloc[100] - 0.5) < 1e-9 and abs(c.iloc[350] - raw.iloc[350]) < 1e-9
    assert abs(c.iloc[300] / c.iloc[299] - 1) < 0.15


def test_universe_and_features_end_to_end(tmp_db):
    syms, days = make_synthetic_market(tmp_db, n_symbols=30, n_days=600)
    refresh_factors(tmp_db)
    as_of = days[-1].date()
    uni = build_universe(tmp_db, as_of, min_turnover_inr=1.0, min_history=250)
    assert len(uni) >= 28                      # a random walk may drift under the Rs 20 floor
    feat = build_features(tmp_db, as_of, min_turnover_inr=1.0)
    assert len(feat) == len(uni)
    r = feat.set_index("symbol").loc["S05"]
    for col in ("mom_12_1", "vol_250", "adv20_inr", "sales_ttm", "pat_ttm", "roe", "pe_ttm",
                "z_quality", "z_value", "z_momentum", "z_lowrisk", "f_score", "promoter_pct"):
        assert pd.notna(r[col]), col
    assert r["f_known"] >= 5 and r["buckets_known"] == 4 and r["rankable"] == 1
    # PIT: statements for FY2021 (visible from 2021-05-30) must not be used on 2021-04-30
    early = build_features(tmp_db, date(2021, 4, 30), min_turnover_inr=1.0, store=False).set_index("symbol")
    late = build_features(tmp_db, date(2021, 6, 30), min_turnover_inr=1.0, store=False).set_index("symbol")
    assert early.loc["S05", "sales_ttm"] < late.loc["S05", "sales_ttm"]
    stored = query(tmp_db, "SELECT count(*) FROM features WHERE as_of = ?", [as_of]).iloc[0, 0]
    assert stored == len(uni)


def test_zscore_grouped_fallback():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0, 5.0, 6.0, 7.0, 8.0, 9.0], index=list("abcdefghij"))
    g = pd.Series(["x"] * 9 + ["y"], index=s.index)
    z = zscore_grouped(s, g, min_group=5)
    assert z.notna().all() and abs(z["e"]) <= 4
    w = winsorise(s)
    assert w["e"] < 100
