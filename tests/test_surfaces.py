from datetime import date, datetime

from fastapi.testclient import TestClient

from eqr.spine.adjust import refresh_factors
from eqr.features.build import build_features
from eqr.strategy.rank import rank_sleeve
from eqr.strategy.regime import store_regime
from eqr.strategy.sleeves import SleeveConfig
from eqr.surfaces.digest import build_digest
from eqr.surfaces.md import render
from eqr.surfaces.queries import advisor_evidence
from tests.conftest import make_synthetic_market


def _prep(con):
    syms, days = make_synthetic_market(con, n_symbols=15, n_days=500)
    refresh_factors(con)
    as_of = days[-1].date()
    build_features(con, as_of, min_turnover_inr=1.0)
    store_regime(con)
    cfg = SleeveConfig.L(top_n=5); cfg.min_turnover_inr = 1.0
    rank_sleeve(con, cfg, as_of)
    return as_of


def test_web_pages_and_advisor(tmp_db, monkeypatch):
    as_of = _prep(tmp_db)
    tmp_db.close()                                   # the app opens its own read-only connections
    monkeypatch.setenv("EQR_ADVISOR_TOKEN", "secret")
    from eqr.surfaces.web.app import app
    c = TestClient(app)
    assert c.get("/").status_code == 200 and "Sleeve L" in c.get("/").text
    r = c.get("/ranks?sleeve=L"); assert r.status_code == 200 and "S0" in r.text
    r = c.get("/symbol/S05"); assert r.status_code == 200 and "Quarterly" in r.text and "<svg" in r.text
    assert c.get("/symbol/NOPE").status_code == 404
    assert c.get("/health").json()["status"] in ("ok", "degraded")
    assert c.get("/advisor/v1/evidence/S05").status_code == 401
    r = c.get("/advisor/v1/evidence/S05", headers={"Authorization": "Bearer secret"})
    j = r.json()
    assert r.status_code == 200 and j["status"] in ("OK", "STALE") and j["sleeve_L"]["rank"] >= 1
    assert j["sleeve_L"]["validated"] is False                  # nothing validated yet -> never claims edge
    assert j["sleeve_L"]["claim_state"] == "DIAGNOSTIC"          # no validation run
    assert ">VALIDATED<" not in c.get("/").text                 # no bare VALIDATED pill on any surface
    r = c.get("/advisor/v1/evidence/NOPE", headers={"Authorization": "Bearer secret"})
    assert r.json()["status"] == "UNKNOWN"
    r = c.get("/advisor/v1/ranks/L", headers={"Authorization": "Bearer secret"})
    assert len(r.json()["ranks"]) >= 5


def test_claim_state_shows_provisional_not_validated_on_a_passing_backtest(tmp_db):
    _prep(tmp_db)
    tmp_db.execute("INSERT INTO backtests (run_id, sleeve, params, verdict, created_at) "
                   "VALUES ('v1', 'L', '{}', 'VALIDATED', ?)", [datetime.now()])
    j = advisor_evidence(tmp_db, "S05")
    assert j["sleeve_L"]["claim_state"] == "PROVISIONAL" and j["sleeve_L"]["validated"] is False
    assert "provisional" in build_digest(tmp_db)
    tmp_db.close()
    from eqr.surfaces.web.app import app
    html = TestClient(app).get("/").text
    assert "PROVISIONAL" in html and "bar PASSED" in html and ">VALIDATED<" not in html


def test_digest_and_markdown(tmp_db):
    _prep(tmp_db)
    text = build_digest(tmp_db)
    assert "eqr digest" in text and "Sleeve L" in text
    h = render("# T\n\n| a | b |\n|---|---|\n| 1 | **2** |\n\n- x\n- y\n\npara `c`")
    assert "<h1>T</h1>" in h and "<table>" in h and "<strong>2</strong>" in h and "<li>y</li>" in h and "<code>c</code>" in h
