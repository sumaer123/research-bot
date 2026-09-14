"""End-to-end engine tests on the synthetic market: metrics -> ratings -> ledger; determinism;
no-look-ahead; planted quality vs planted fraud; calibration protocol on a planted history."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_synthetic_market


def _plant(con, sym: str, kind: str):
    """Rewrite one symbol's statements so it is unmistakably clean/cheap (quality) or fraudulent."""
    from eqr.store import upsert
    rows = con.execute("SELECT * FROM statements WHERE symbol = ?", [sym]).df()
    if kind == "quality":
        # huge cash generation, no debt, high margins: CFO > PAT, FCF high, borrowings 0
        rows.loc[rows.line_item == "cash_from_operating_activity", "value"] *= 3
        rows.loc[rows.line_item == "free_cash_flow", "value"] *= 4
        rows.loc[rows.line_item == "borrowings", "value"] = 1.0
        rows.loc[rows.line_item == "operating_profit", "value"] *= 1.8
        rows.loc[rows.line_item == "net_profit", "value"] *= 1.8
    else:
        # fraud: profits without cash, ballooning receivables (debtor_days), leverage up
        rows.loc[rows.line_item == "cash_from_operating_activity", "value"] *= -0.5
        rows.loc[rows.line_item == "free_cash_flow", "value"] *= -1
        rows.loc[rows.line_item == "net_profit", "value"] *= 2.5
        rows.loc[rows.line_item == "borrowings", "value"] *= 4
        dd = []
        for i, fy in enumerate(sorted(rows[rows.stmt == "pl_a"].period_end.unique())):
            dd.append({"symbol": sym, "basis": "consolidated", "stmt": "ratios_a", "period_end": fy, "line_item": "debtor_days",
                       "value": 40.0 * (1.9 ** i), "fetched_at": datetime.now(), "visible_from": pd.Timestamp(fy) + timedelta(days=60)})
        rows = pd.concat([rows, pd.DataFrame(dd)])
    upsert(con, "statements", rows)


def _enrich(con, syms, days):
    """Give the thin synthetic statements the depth the engine needs: 8 fiscal years, the
    working-capital / tax / investing items, real NSE industry strings, and a recent FY."""
    from eqr.store import upsert
    rng = np.random.default_rng(11)
    rows = []
    fys = [date(2015 + k, 3, 31) for k in range(8)]              # FY2015..FY2022
    for j, sym in enumerate(syms):
        base = 1000.0 * (1 + j)
        for k, fy in enumerate(fys):
            g = 1.08 ** k
            vis = fy + timedelta(days=60) if fy.year < 2022 else date(2022, 4, 10)   # FY2022 visible inside the fixture
            items = [("pl_a", "sales", base * g), ("pl_a", "net_profit", base * g * 0.1), ("pl_a", "operating_profit", base * g * 0.2),
                     ("pl_a", "depreciation", base * g * 0.03), ("pl_a", "other_income", base * g * 0.01), ("pl_a", "interest", base * g * 0.02),
                     ("pl_a", "profit_before_tax", base * g * 0.14), ("pl_a", "tax_pct", 25.0), ("pl_a", "eps_in_rs", 10.0 * g),
                     ("pl_a", "dividend_payout_pct", 25.0), ("pl_a", "expenses", base * g * 0.8),
                     ("bs_a", "equity_capital", 100.0), ("bs_a", "reserves", base * 0.5 * g), ("bs_a", "borrowings", base * 0.3),
                     ("bs_a", "other_liabilities", base * 0.2), ("bs_a", "total_liabilities", base * 1.2 * g), ("bs_a", "fixed_assets", base * 0.5),
                     ("bs_a", "cwip", base * 0.02), ("bs_a", "investments", base * 0.05), ("bs_a", "other_assets", base * 0.4),
                     ("bs_a", "total_assets", base * 1.2 * g),
                     ("cf_a", "cash_from_operating_activity", base * g * 0.12), ("cf_a", "cash_from_investing_activity", -base * g * 0.05),
                     ("cf_a", "cash_from_financing_activity", -base * g * 0.04), ("cf_a", "net_cash_flow", base * g * 0.03),
                     ("cf_a", "free_cash_flow", base * g * 0.08),
                     ("ratios_a", "roce_pct", 15.0 + j % 5), ("ratios_a", "roe_pct", 14.0), ("ratios_a", "debtor_days", 40.0 + rng.normal(0, 2)),
                     ("ratios_a", "inventory_days", 30.0), ("ratios_a", "days_payable", 35.0), ("ratios_a", "cash_conversion_cycle", 35.0),
                     ("ratios_a", "working_capital_days", 30.0)]
            for stmt, item, v in items:
                rows.append({"symbol": sym, "basis": "consolidated", "stmt": stmt, "period_end": fy, "line_item": item,
                             "value": v, "fetched_at": datetime.now(), "visible_from": vis})
    upsert(con, "statements", pd.DataFrame(rows))
    inds = ["Automobiles", "Capital Goods", "Pharmaceuticals & Biotechnology", "IT - Software", "Chemicals"]
    con.execute("UPDATE instruments SET industry = CASE " + " ".join(
        f"WHEN symbol = '{s}' THEN '{inds[i % len(inds)]}'" for i, s in enumerate(syms)) + " END")


@pytest.fixture()
def market(tmp_db):
    syms, days = make_synthetic_market(tmp_db, n_symbols=40, n_days=600)
    _enrich(tmp_db, syms, days)
    from eqr.features.build import build_features
    from eqr.features.panel import load_panel, window_start
    from eqr.spine.universe import month_end_sessions
    _plant(tmp_db, "S05", "quality")
    _plant(tmp_db, "S07", "fraud")
    dates = month_end_sessions(tmp_db, days[300].date(), days[-1].date())
    panel = load_panel(tmp_db, window_start(dates[0], 420), dates[-1], series=("EQ", "BE", "BZ"))
    for d in dates:
        build_features(tmp_db, d, panel=panel)
    return tmp_db, syms, days, dates


def test_metrics_and_ratings_end_to_end(market):
    con, syms, days, dates = market
    from eqr.fundamentals.build import build_metrics, load_metrics, METRICS_VERSION
    from eqr.rating import engine as eng
    d = dates[-1]
    wide = build_metrics(con, d, store=True)
    assert len(wide) >= 30 and "fv_base" in wide.columns and "spread_ttm" in wide.columns
    n = con.execute("SELECT count(*) FROM fund_metrics WHERE as_of = ? AND engine_version = ?", [d, METRICS_VERSION]).fetchone()[0]
    assert n == sum(len(r) for r in [wide.columns]) * len(wide) or n > len(wide) * 50
    again = load_metrics(con, d)
    assert set(again.index) == set(wide.index)
    res = eng.rate_universe(con, d, store=True)
    assert len(res) >= 30
    rows = con.execute("SELECT count(*), sum(CASE WHEN status='RATED' THEN 1 ELSE 0 END) FROM ratings WHERE as_of = ?", [d]).fetchone()
    assert rows[0] == len(res) and rows[1] >= 20
    r = {x.symbol: x for x in res}
    # every rated name has a verdict, a score in [0,100], six pillars, a manifest sha and a DCI in [0,1]
    for x in res:
        assert x.decision.verdict in ("CONVICTION_BUY", "SPECULATIVE_BUY", "HOLD", "TRIM", "SELL", "NO_RATING")
        assert set(x.pillars) == {"P1_MOAT", "P2_BALANCE", "P3_EARNINGS", "P4_GROWTH", "P5_MANAGEMENT", "P6_VALUATION"}
        assert 0 <= x.confidence.dci <= 1 and len(x.manifest_sha) == 64
        if x.score is not None:
            assert 0 <= x.score <= 100
    # planted fraud: hard forensic flag and a SELL regardless of score
    fraud = r["S07"]
    assert any(f.tier == "HARD" for f in fraud.red_flags), [f.code for f in fraud.red_flags]
    assert fraud.decision.verdict == "SELL" and fraud.decision.rule_id == "R1_HARD_FLAG"
    # planted quality: best-in-class P2/P3, no hard flags, higher score than the fraud name
    q = r["S05"]
    assert not any(f.tier == "HARD" for f in q.red_flags)
    assert q.pillars["P2_BALANCE"].score > 70 and q.pillars["P3_EARNINGS"].score > 60
    assert q.score > fraud.score


def test_determinism_and_no_lookahead(market):
    con, syms, days, dates = market
    from eqr.rating import engine as eng
    d = dates[-1]
    a = {x.symbol: x for x in eng.rate_universe(con, d, store=False, recompute_metrics=True, prev={})}
    b = {x.symbol: x for x in eng.rate_universe(con, d, store=False, recompute_metrics=True, prev={})}
    assert all(a[s].manifest_sha == b[s].manifest_sha for s in a)
    # push one statement's visible_from past as_of: the manifest changes and coverage drops for that name
    sym = "S03"
    fy = con.execute("SELECT max(period_end) FROM statements WHERE symbol = ? AND stmt = 'pl_a'", [sym]).fetchone()[0]
    con.execute("UPDATE statements SET visible_from = ? WHERE symbol = ? AND period_end = ?", [d + timedelta(days=1), sym, fy])
    c = {x.symbol: x for x in eng.rate_universe(con, d, store=False, recompute_metrics=True, prev={})}
    assert c[sym].manifest_sha != a[sym].manifest_sha
    assert c[sym].confidence.component_coverage <= a[sym].confidence.component_coverage + 1e-9


def test_hysteresis_uses_previous_stored_verdict(market):
    con, syms, days, dates = market
    from eqr.rating import engine as eng
    d0, d1 = dates[-2], dates[-1]
    eng.rate_universe(con, d0, store=True)
    prev = eng.previous_verdicts(con, d1, "r1", "base")
    assert prev and all(v in ("CONVICTION_BUY", "SPECULATIVE_BUY", "HOLD", "TRIM", "SELL") for v in prev.values())
    res = eng.rate_universe(con, d1, store=True)
    assert any(x.manifest.get("prev_verdict") is not None for x in res)


def test_ledger_publish_is_append_only_and_matures(market):
    con, syms, days, dates = market
    from eqr.rating import engine as eng, ledger
    d = dates[-3]
    eng.rate_universe(con, d, store=True)
    out = ledger.publish(con, d, "r1")
    assert out["published"] > 0
    again = ledger.publish(con, d, "r1")
    assert again["published"] == 0
    n0 = con.execute("SELECT count(*) FROM rating_ledger WHERE as_of = ?", [d]).fetchone()[0]
    # nothing has matured yet with a 252-session horizon inside a 600-day fixture starting at day 300 -> stays pending
    m = ledger.mature(con, "r1", today=days[-1].date())
    pend = con.execute("SELECT count(*) FROM rating_ledger WHERE outcome = 'pending'").fetchone()[0]
    assert n0 == con.execute("SELECT count(*) FROM rating_ledger WHERE as_of = ?", [d]).fetchone()[0]
    # shrink the horizon and mature: every row leaves 'pending' with a forward return
    con.execute("UPDATE rating_ledger SET horizon_days = 20")
    m = ledger.mature(con, "r1", today=days[-1].date())
    assert m["filled"] == n0
    rows = con.execute("SELECT outcome, fwd_return FROM rating_ledger WHERE as_of = ?", [d]).fetchall()
    assert all(o in ("hit", "miss", "delisted") for o, _ in rows) and all(f is not None for _, f in rows)
    rep = ledger.report(con, "r1", min_matured=1, min_per_tier=1)
    assert rep["status"] == "OK" and rep["tiers"]


def test_calibration_protocol_on_planted_history(tmp_db):
    """A planted monotone signal passes the tier/decile checks; a random history fails the bar."""
    from eqr.rating.calibrate import CalibrationConfig, run_calibration, nw_tstat, ic_series
    rng = np.random.default_rng(3)
    dates = [date(2018 + i // 12, i % 12 + 1, 28) for i in range(84)]          # 2018-01 .. 2024-12
    syms = [f"S{i:02d}" for i in range(80)]
    rows = []
    for d in dates:
        for v in ("base", "quality_tilt", "value_tilt", "no_valuation"):
            for s in syms:
                score = rng.uniform(20, 95)
                mos = rng.normal(0, 0.3)
                noise = rng.normal(0, 0.15)
                fwd = 0.004 * (score - 55) + 0.1 * mos + noise           # planted: higher score/MoS -> higher return
                verdict = ("CONVICTION_BUY" if score >= 80 and mos >= 0.2 else "SPECULATIVE_BUY" if score >= 75
                           else "SELL" if score < 35 else "TRIM" if score < 50 or mos < -0.25 else "HOLD")
                rows.append({"as_of": d, "variant": v, "symbol": s, "profile": rng.choice(["GENERAL", "BANK", "PHARMA"]),
                             "status": "RATED", "score": score, "verdict": verdict, "rule_id": "R", "mos": mos,
                             "dci": 0.8, "band": rng.choice(["HIGH", "MED", "LOW"]), "coverage": rng.uniform(0.7, 1.0),
                             "hard": "", "soft": "", "fwd": fwd, "bench": 0.0, "matured": d + timedelta(days=365),
                             "fwd36": fwd * 3, "bench36": 0.0})
    hist = pd.DataFrame(rows); hist["excess"] = hist.fwd - hist.bench; hist["excess36"] = hist.fwd36 - hist.bench36
    cfg = CalibrationConfig(start=dates[0], end=dates[-1], holdout_start=date(2024, 1, 1), fold_years=(2020, 2021, 2022, 2023))
    out = run_calibration(tmp_db, cfg, hist=hist, store=True)
    m = out["metrics"]
    assert m["decile_monotonic_overall"] is True and m["ic_mean"] > 0.3 and m["long_short_pp"] > 0.05
    assert m["tiers_ordered"] is True and out["acceptance"]["ic_mean_min"]["pass"] is True
    assert out["acceptance"]["holdout_long_short_positive"]["pass"] is True
    assert tmp_db.execute("SELECT count(*) FROM rating_calibrations").fetchone()[0] == 1
    # random history: no IC, bar fails
    hist2 = hist.copy(); hist2["fwd"] = rng.normal(0, 0.2, len(hist2)); hist2["excess"] = hist2.fwd
    out2 = run_calibration(tmp_db, cfg, hist=hist2, store=False)
    assert out2["verdict"] == "NOT VALIDATED" and abs(out2["metrics"]["ic_mean"]) < 0.05
    # Newey-West hand value on a constant series is +inf-ish; on an i.i.d. series ~ mean/se
    x = pd.Series(rng.normal(0.05, 0.1, 200))
    t = nw_tstat(x, lag=0)
    assert abs(t - x.mean() / (x.std(ddof=0) / np.sqrt(len(x)))) < 1e-6
