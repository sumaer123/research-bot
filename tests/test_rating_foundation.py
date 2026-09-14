"""Foundation invariants: sector map covers every live industry, weights sum to 1, pillar
scoring shrinks to the prior and never renormalises, base loader is PIT and split-invariant,
and the layering rule (strategy/features never import rating/fundamentals/research)."""
from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eqr.rating import sector
from eqr.rating.pillars import COMPONENTS, COMPONENT_BY_NAME, component_scores, composite, map_score, pillar_scores_for
from eqr.rating.model import OK, UNKNOWN, NA

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1] / "eqr"


# ---------------------------------------------------------------------------- sector

def test_every_live_industry_is_mapped():
    live = [l.strip() for l in (FIXTURES / "nse_industries.txt").read_text().splitlines() if l.strip()]
    assert len(live) >= 70
    missing = [i for i in live if i not in sector.SECTOR_PROFILE_MAP]
    assert missing == []


def test_profile_for_bank_nbfc_it_pharma_cyclical_general_and_unmapped():
    assert sector.profile_for("Banks")[0] == sector.BANK
    assert sector.profile_for("Finance")[0] == sector.NBFC_FIN
    assert sector.profile_for("IT - Software")[0] == sector.IT_SERVICES
    assert sector.profile_for("Pharmaceuticals & Biotechnology")[0] == sector.PHARMA
    assert sector.profile_for("Metals & Mining")[0] == sector.CYCLICAL
    assert sector.profile_for("Automobiles")[0] == sector.GENERAL
    p, notes = sector.profile_for("Something New")
    assert p == sector.GENERAL and "profile_unmapped" in notes
    # deposits force BANK for a financial-industry name (small finance banks land in Finance)
    assert sector.profile_for("Finance", has_deposits=True)[0] == sector.BANK
    p, notes = sector.profile_for("Automobiles", has_deposits=True)
    assert p == sector.GENERAL and "deposits_outside_financial_industry" in notes


def test_weights_sum_to_one_for_every_profile_and_variant():
    for p in sector.PROFILES:
        for v in sector.VARIANTS:
            w = sector.profile_weights(p, v)
            assert set(w) == set(sector.PILLARS)
            assert abs(sum(w.values()) - 1.0) < 1e-9, (p, v, w)
            assert all(x >= 0 for x in w.values())


# ---------------------------------------------------------------------------- pillars

def test_catalogue_has_unique_names_and_every_pillar_in_every_profile():
    assert len({c.name for c in COMPONENTS}) == len(COMPONENTS)
    for p in sector.PROFILES:
        for pillar in sector.PILLARS:
            assert any(c.pillar == pillar and c.applies(p, "r1", "base") for c in COMPONENTS), (p, pillar)


def test_llm_components_only_in_with_qual_and_r3():
    llm = [c for c in COMPONENTS if c.llm]
    assert llm
    for c in llm:
        assert not c.applies("GENERAL", "r3", "base")
        assert c.applies("GENERAL", "r3", "with_qual")
        assert not c.applies("GENERAL", "r1", "with_qual")


def test_map_score_interpolates_and_clips():
    pts = ((0.0, 100), (1.0, 85), (2.0, 65), (3.0, 45), (4.0, 25), (6.0, 0))
    assert map_score(-5, pts) == 100
    assert map_score(0.5, pts) == pytest.approx(92.5)
    assert map_score(10, pts) == 0


def _frame(n=20, seed=1):
    rng = np.random.default_rng(seed)
    idx = [f"S{i:02d}" for i in range(n)]
    raw = pd.DataFrame(index=idx)
    raw["roce_median_10y"] = rng.normal(0.15, 0.05, n)
    raw["net_debt_ebitda"] = rng.uniform(0, 5, n)
    raw["int_cover_ttm"] = rng.uniform(1, 20, n)
    raw["int_cover_min_5y"] = rng.uniform(1, 10, n)
    raw["altman_zpp"] = rng.uniform(0.5, 8, n)
    raw["debt_equity"] = rng.uniform(0, 2, n)
    raw["de_trend_3y"] = rng.normal(0, 0.1, n)
    raw["net_debt_fcf_years"] = rng.uniform(0, 8, n)
    raw["spread_median_5y"] = rng.normal(0.03, 0.04, n)
    raw["adverse_events_90d_clean"] = 1.0
    prof = pd.Series("GENERAL", index=idx)
    return raw, prof


def test_component_scores_pct_map_binary_and_priors():
    raw, prof = _frame()
    sc = component_scores(raw, prof, prof, "r1", "base")
    assert sc["roce_median_10y"].between(0, 100).all()
    assert sc["net_debt_ebitda"].between(0, 100).all()
    assert (sc["adverse_events_90d_clean"] == 100).all()
    # a metric nobody has is all-NaN with an empty prior
    assert sc["gnpa_pct"].isna().all()
    assert sc.attrs["priors"]["roce_median_10y"]["GENERAL"] == pytest.approx(50, abs=5)


def test_pillar_shrinks_unknown_to_prior_and_never_renormalises():
    raw, prof = _frame()
    sc = component_scores(raw, prof, prof, "r1", "base")
    sym = "S00"
    p_full = pillar_scores_for(sym, sc, raw, "GENERAL", "r1", "base")
    p2 = p_full["P2_BALANCE"]
    known = [c for c in p2.components if c.status == OK]
    unknown = [c for c in p2.components if c.status == UNKNOWN]
    assert known and unknown
    # exact arithmetic: (sum w*score over known + sum w*prior over unknown) / total weight
    num = sum(c.weight * c.score for c in p2.components)
    assert p2.score == pytest.approx(num / p2.weight_total)
    assert all(c.shrunk_to_prior for c in unknown) and all(c.score == c.prior for c in unknown)
    # remove one known component -> score moves toward the prior by exactly w*(c - prior)/total
    c0 = known[0]
    raw2 = raw.copy(); raw2.loc[sym, c0.name] = np.nan
    sc2 = component_scores(raw2, prof, prof, "r1", "base")
    p2b = pillar_scores_for(sym, sc2, raw2, "GENERAL", "r1", "base")["P2_BALANCE"]
    prior2 = next(c.prior for c in p2b.components if c.name == c0.name)
    assert p2b.score == pytest.approx(p2.score - c0.weight * (c0.score - prior2) / p2.weight_total, abs=1e-6)
    assert p2b.weight_known == pytest.approx(p2.weight_known - c0.weight)


def test_pillar_unknown_when_under_half_known():
    raw, prof = _frame()
    sc = component_scores(raw, prof, prof, "r1", "base")
    p = pillar_scores_for("S00", sc, raw, "GENERAL", "r1", "base")
    # P1 only has spread_median_5y (w2) + roce_median_10y (w1) known of ~14 weight -> UNKNOWN
    assert p["P1_MOAT"].status == UNKNOWN
    assert p["P1_MOAT"].score is not None
    assert p["P3_EARNINGS"].status == UNKNOWN


def test_composite_is_weighted_mean_over_all_pillars():
    raw, prof = _frame()
    sc = component_scores(raw, prof, prof, "r1", "base")
    p = pillar_scores_for("S01", sc, raw, "GENERAL", "r1", "base")
    w = sector.profile_weights("GENERAL")
    S = composite(p, w)
    assert S == pytest.approx(sum(w[k] * p[k].score for k in w))


def test_financial_profile_never_gets_nonfinancial_components_and_vice_versa():
    raw, prof = _frame()
    prof2 = prof.copy(); prof2["S00"] = "BANK"
    raw.loc["S00", "gnpa_pct"] = 2.0
    sc = component_scores(raw, prof2, prof2, "r1", "base")
    bank = pillar_scores_for("S00", sc, raw, "BANK", "r1", "base")
    names = {c.name for pl in bank.values() for c in pl.components}
    assert "gnpa_pct" in names and "net_debt_ebitda" not in names and "beneish_level" not in names
    gen = pillar_scores_for("S01", sc, raw, "GENERAL", "r1", "base")
    names = {c.name for pl in gen.values() for c in pl.components}
    assert "net_debt_ebitda" in names and "gnpa_pct" not in names and "cet1_pct" not in names


# ---------------------------------------------------------------------------- base loader (PIT + splits)

def test_load_inputs_is_pit_and_mcap_series_split_invariant(tmp_db):
    from tests.conftest import make_synthetic_market
    from eqr.fundamentals.base import load_inputs, mcap_series
    syms, days = make_synthetic_market(tmp_db, n_symbols=6, n_days=600)
    # FY2021 (period_end 2021-03-31) is visible from 2021-05-30: not on 2021-04-30
    early = load_inputs(tmp_db, date(2021, 4, 30), ["S02"], with_xbrl=False)["S02"]
    late = load_inputs(tmp_db, date(2021, 6, 30), ["S02"], with_xbrl=False)["S02"]
    assert early.latest_period() == date(2020, 3, 31)
    assert late.latest_period() == date(2021, 3, 31)
    assert early.profile == "GENERAL" and "profile_unmapped" in early.notes   # IND0 is not an NSE string
    # S01 has a 1:1 bonus at day 300: raw close halves, equity capital in the fixture stays 100 ->
    # emulate the bonus on the statements and check mcap continuity through the event
    ex = days[300].date()
    fy_before = [d for d in late.annual.index if d.date() < ex]
    fy_after = [d for d in late.annual.index if d.date() >= ex]
    assert fy_before and fy_after
    s01 = load_inputs(tmp_db, days[-1].date(), ["S01"], with_xbrl=False)["S01"]
    ann = s01.annual.copy()
    ann.loc[[d for d in ann.index if d.date() >= ex], "equity_capital"] = 200.0     # bonus doubles capital
    m = mcap_series(tmp_db, "S01", ann, 10.0, days[-1].date())
    assert m.notna().sum() >= 2
    # a price series that is a random walk keeps mcap within a plausible band; the bonus itself
    # must NOT halve mcap: compare the FY just after the bonus against the raw-close x old-shares view
    d_after = min(d for d in ann.index if d.date() >= ex)
    raw_close = tmp_db.execute("SELECT close FROM prices_daily WHERE symbol='S01' AND trade_date <= ? "
                               "ORDER BY trade_date DESC LIMIT 1", [d_after.date()]).fetchone()[0]
    assert m[d_after] == pytest.approx(raw_close * 200.0 / 10.0)


def test_split_face_value_history_parses_combined_kind(tmp_db):
    from eqr.fundamentals.base import face_value_history
    tmp_db.execute("INSERT INTO adj_factors VALUES ('X', DATE '2025-06-16', 0.1, 933.1, 9331.0, 'split 2->1; bonus 4:1 gap 0.102')")
    tmp_db.execute("INSERT INTO adj_factors VALUES ('X', DATE '2016-09-08', 0.1, 100.0, 1000.0, 'split 10->2; bonus 1:1')")
    hist = face_value_history(tmp_db, "X", 1.0, date(2026, 9, 11))
    assert hist == [(date(2025, 6, 16), 2.0), (date(2016, 9, 8), 10.0)]


def test_borrowing_singular_is_coalesced(tmp_db):
    from datetime import datetime
    from eqr.fundamentals.base import load_inputs
    from eqr.store import upsert
    rows = []
    for fy, v in [(date(2023, 3, 31), 50.0), (date(2024, 3, 31), 60.0)]:
        for item, val in [("sales", 100.0), ("net_profit", 10.0), ("equity_capital", 10.0), ("reserves", 40.0),
                          ("borrowing", v), ("total_assets", 200.0)]:
            rows.append({"symbol": "B1", "basis": "consolidated", "stmt": "bs_a" if item != "sales" and item != "net_profit" else "pl_a",
                         "period_end": fy, "line_item": item, "value": val, "fetched_at": datetime.now(),
                         "visible_from": fy + timedelta(days=60)})
    upsert(tmp_db, "statements", pd.DataFrame(rows))
    upsert(tmp_db, "instruments", pd.DataFrame([{"symbol": "B1", "name": "B1", "series": "EQ", "face_value": 10.0,
                                                 "industry": "Automobiles", "as_of": date(2024, 6, 30)}]))
    inp = load_inputs(tmp_db, date(2024, 6, 30), ["B1"], with_xbrl=False)["B1"]
    assert inp.borrowings() == 60.0 and inp.profile == "GENERAL"


# ---------------------------------------------------------------------------- layering

def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(("." * node.level) + node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


@pytest.mark.parametrize("pkg", ["spine", "store", "features", "strategy"])
def test_lower_layers_never_import_rating_fundamentals_or_research(pkg):
    forbidden = ("rating", "fundamentals", "research", "anthropic")
    for py in (ROOT / pkg).rglob("*.py"):
        for imp in _imports(py):
            leaf = imp.lstrip(".").split(".")
            assert not any(f in leaf for f in forbidden), f"{py} imports {imp}"


def test_rating_and_fundamentals_never_import_research_or_strategy():
    for pkg in ("rating", "fundamentals"):
        for py in (ROOT / pkg).rglob("*.py"):
            for imp in _imports(py):
                leaf = imp.lstrip(".").split(".")
                assert "research" not in leaf and "strategy" not in leaf and "anthropic" not in leaf, f"{py} imports {imp}"
