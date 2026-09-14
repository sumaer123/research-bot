"""Tests for ratings surface: queries, rendering, web routes."""
import json
from datetime import date, datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from eqr.spine.adjust import refresh_factors
from eqr.features.build import build_features
from eqr.strategy.rank import rank_sleeve
from eqr.strategy.regime import store_regime
from eqr.strategy.sleeves import SleeveConfig
from eqr.store import upsert
from eqr.surfaces.queries import latest_rating, ratings_table, rating_history, engine_claim_state
from eqr.surfaces.report import decision_onepager_md, telegram_card
from tests.conftest import make_synthetic_market


def _prep(con):
    """Prepare database with synthetic data."""
    syms, days = make_synthetic_market(con, n_symbols=15, n_days=500)
    refresh_factors(con)
    as_of = days[-1].date()
    build_features(con, as_of, min_turnover_inr=1.0)
    store_regime(con)
    cfg = SleeveConfig.L(top_n=5)
    cfg.min_turnover_inr = 1.0
    rank_sleeve(con, cfg, as_of)
    return as_of, syms


def test_latest_rating_query(tmp_db):
    """Test latest_rating query with synthetic data."""
    as_of, syms = _prep(tmp_db)

    # Insert a synthetic rating row
    rating_data = {
        "symbol": syms[0],
        "as_of": as_of,
        "engine_version": "r1",
        "variant": "base",
        "status": "RATED",
        "rating": "HOLD",
        "score": 65.5,
        "confidence": 0.75,
        "confidence_band": "MED",
        "coverage": 0.88,
        "pillars_json": json.dumps({
            "moat_quality": {"score": 75, "coverage": 0.9, "weight_known": 0.2, "components": []},
            "balance_sheet": {"score": 68, "coverage": 0.85, "weight_known": 0.15, "components": []}
        }),
        "gates_json": json.dumps([]),
        "manifest_json": json.dumps({"test": True}),
        "manifest_sha": "abc123",
        "data_errors_json": json.dumps([]),
        "decision_json": json.dumps({"verdict": "HOLD", "rule_id": "R8"}),
        "rule_id": "R8",
        "profile": "GENERAL",
        "mos_base": 0.12,
        "fv_base": 1500.0,
        "fv_bull": 1800.0,
        "fv_bear": 1200.0,
        "dci_band": "MED",
        "valuation_json": json.dumps({"pe": 18.5}),
        "price": 1350.0,
        "created_at": datetime.now(),
    }
    upsert(tmp_db, "ratings", pd.DataFrame([rating_data]))

    # Query it back
    rating = latest_rating(tmp_db, syms[0])
    assert rating is not None
    assert rating["symbol"] == syms[0]
    assert rating["rating"] == "HOLD"
    assert rating["score"] == 65.5
    assert rating["confidence"] == 0.75
    assert rating["dci_band"] == "MED"
    assert rating["pillars"]["moat_quality"]["score"] == 75
    assert rating["gates"] == []
    assert rating["decision"]["verdict"] == "HOLD"


def test_ratings_table_query(tmp_db):
    """Test ratings_table query returns structured DataFrame."""
    as_of, syms = _prep(tmp_db)

    # Insert two ratings
    for i, sym in enumerate(syms[:2]):
        rating_data = {
            "symbol": sym,
            "as_of": as_of,
            "engine_version": "r1",
            "variant": "base",
            "status": "RATED",
            "rating": "CONVICTION_BUY" if i == 0 else "HOLD",
            "score": 85.0 if i == 0 else 62.0,
            "confidence": 0.88 if i == 0 else 0.70,
            "confidence_band": "HIGH" if i == 0 else "MED",
            "coverage": 0.95,
            "pillars_json": json.dumps({}),
            "gates_json": json.dumps([]),
            "manifest_json": json.dumps({}),
            "manifest_sha": f"sha{i}",
            "data_errors_json": json.dumps([]),
            "decision_json": json.dumps({"verdict": "CONVICTION_BUY" if i == 0 else "HOLD"}),
            "rule_id": "R5" if i == 0 else "R8",
            "profile": "GENERAL",
            "mos_base": 0.25 if i == 0 else 0.08,
            "fv_base": 1500.0,
            "fv_bull": 1800.0,
            "fv_bear": 1200.0,
            "dci_band": "HIGH" if i == 0 else "MED",
            "valuation_json": json.dumps({}),
            "price": 1350.0,
            "created_at": datetime.now(),
        }
        upsert(tmp_db, "ratings", pd.DataFrame([rating_data]))

    # Query all
    tbl = ratings_table(tmp_db)
    assert len(tbl) == 2
    assert list(tbl["symbol"].values) == syms[:2]
    assert "rating" in tbl.columns
    assert "score" in tbl.columns
    assert "mos_base" in tbl.columns
    assert "dci_band" in tbl.columns

    # Query by verdict
    conv_only = ratings_table(tmp_db, verdict="CONVICTION_BUY")
    assert len(conv_only) == 1
    assert conv_only.iloc[0]["rating"] == "CONVICTION_BUY"


def test_rating_history_query(tmp_db):
    """Test rating_history returns recent ratings for a symbol."""
    as_of, syms = _prep(tmp_db)

    # Insert 3 ratings on different dates
    for i in range(3):
        rating_data = {
            "symbol": syms[0],
            "as_of": as_of - timedelta(days=i),
            "engine_version": "r1",
            "variant": "base",
            "status": "RATED",
            "rating": "HOLD" if i == 0 else "TRIM",
            "score": 65.0 - i * 5,
            "confidence": 0.75 - i * 0.05,
            "confidence_band": "MED",
            "coverage": 0.90,
            "pillars_json": json.dumps({}),
            "gates_json": json.dumps([]),
            "manifest_json": json.dumps({}),
            "manifest_sha": f"sha{i}",
            "data_errors_json": json.dumps([]),
            "decision_json": json.dumps({"verdict": "HOLD" if i == 0 else "TRIM"}),
            "rule_id": "R8" if i == 0 else "R4",
            "profile": "GENERAL",
            "mos_base": 0.10 - i * 0.02,
            "fv_base": 1500.0,
            "fv_bull": 1800.0,
            "fv_bear": 1200.0,
            "dci_band": "MED",
            "valuation_json": json.dumps({}),
            "price": 1350.0,
            "created_at": datetime.now(),
        }
        upsert(tmp_db, "ratings", pd.DataFrame([rating_data]))

    # Query history
    hist = rating_history(tmp_db, syms[0], limit=10)
    assert len(hist) == 3
    assert hist.iloc[0]["rating"] == "HOLD"  # Most recent
    assert hist.iloc[2]["rating"] == "TRIM"  # Oldest


def test_engine_claim_state_query(tmp_db):
    """Test engine_claim_state returns correct state."""
    as_of, _ = _prep(tmp_db)

    # No calibration row -> DIAGNOSTIC
    state = engine_claim_state(tmp_db, "r1")
    assert state == "DIAGNOSTIC"

    # Insert a VALIDATED calibration -> PROVISIONAL
    tmp_db.execute("""INSERT INTO rating_calibrations
                      (run_id, engine_version, start_date, end_date, verdict, created_at)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   ["calib_r1", "r1", as_of - __import__('datetime').timedelta(days=30), as_of, "VALIDATED", datetime.now()])

    state = engine_claim_state(tmp_db, "r1")
    assert state == "PROVISIONAL"


def test_decision_onepager_md_rendering(tmp_db):
    """Test Markdown rendering of decision one-pager."""
    as_of, syms = _prep(tmp_db)

    rating_data = {
        "symbol": syms[0],
        "as_of": as_of,
        "engine_version": "r1",
        "variant": "base",
        "status": "RATED",
        "rating": "CONVICTION_BUY",
        "name": "TestCorp",
        "profile": "GENERAL",
        "score": 84.0,
        "confidence": 0.85,
        "dci_band": "HIGH",
        "price": 1350.0,
        "mos_base": 0.27,
        "fv_base": 1910.0,
        "fv_bull": 2350.0,
        "fv_bear": 1420.0,
        "pillars": {
            "moat_quality": {
                "score": 82,
                "coverage": 0.9,
                "weight_known": 0.2,
                "components": [
                    {"name": "ROIC_WACC", "raw": 7.3, "score": 85, "status": "KNOWN"}
                ]
            }
        },
        "gates": [],
        "data_errors": [],
        "decision": {"verdict": "CONVICTION_BUY", "rule_id": "R5"},
        "manifest_sha": "3f9a...",
    }

    md = decision_onepager_md(rating_data)
    assert "CONVICTION_BUY" in md
    assert "TestCorp" in md
    assert "84" in md
    assert "27%" in md
    assert "1,910" in md  # Formatted with comma
    assert "moat_quality" in md
    assert "R5" in md


def test_telegram_card_rendering(tmp_db):
    """Test 5-line Telegram card rendering."""
    rating_data = {
        "symbol": "TESTCORP",
        "rating": "HOLD",
        "score": 62.0,
        "mos_base": 0.08,
        "fv_base": 1500.0,
        "dci_band": "MED",
        "gates": [
            {"code": "OTHER_INCOME_25_50", "tier": "WATCH", "value": 18}
        ],
    }

    card = telegram_card(rating_data)
    lines = card.split("<br>")
    assert len(lines) == 5
    assert "HOLD" in lines[0]
    assert "TESTCORP" in lines[0]
    assert "62" in lines[1]
    assert "MED" in lines[3]


def test_web_routes_decision_and_ratings(tmp_db, monkeypatch):
    """Test web routes for /decision/{symbol} and /ratings."""
    as_of, syms = _prep(tmp_db)

    # Insert ratings
    rating_data = {
        "symbol": syms[0],
        "as_of": as_of,
        "engine_version": "r1",
        "variant": "base",
        "status": "RATED",
        "rating": "HOLD",
        "score": 65.0,
        "confidence": 0.75,
        "confidence_band": "MED",
        "coverage": 0.88,
        "pillars_json": json.dumps({}),
        "gates_json": json.dumps([]),
        "manifest_json": json.dumps({}),
        "manifest_sha": "sha1",
        "data_errors_json": json.dumps([]),
        "decision_json": json.dumps({"verdict": "HOLD"}),
        "rule_id": "R8",
        "profile": "GENERAL",
        "mos_base": 0.12,
        "fv_base": 1500.0,
        "fv_bull": 1800.0,
        "fv_bear": 1200.0,
        "dci_band": "MED",
        "valuation_json": json.dumps({}),
        "price": 1350.0,
        "created_at": datetime.now(),
    }
    upsert(tmp_db, "ratings", pd.DataFrame([rating_data]))
    tmp_db.close()

    monkeypatch.setenv("EQR_ADVISOR_TOKEN", "secret")
    from eqr.surfaces.web.app import app
    c = TestClient(app)

    # Test /decision/{symbol} route
    r = c.get(f"/decision/{syms[0]}")
    assert r.status_code == 200
    assert "HOLD" in r.text or "65" in r.text

    # Test /decision/{symbol}.md route
    r = c.get(f"/decision/{syms[0]}.md")
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("content-type", "")

    # Test /ratings route
    r = c.get("/ratings")
    assert r.status_code == 200
    assert syms[0] in r.text

    # Test /ratings.csv route
    r = c.get("/ratings.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "symbol" in r.text.lower()

    # Test 404 on unknown symbol
    assert c.get("/decision/NOPE").status_code == 404
