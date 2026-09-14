import json
from datetime import date

from eqr.research.schema import validate_dossier, SCHEMA
from eqr.research.dossier import render_markdown, run_dossier, _extract_json
from eqr.research.pack import build_pack
from eqr.spine.adjust import refresh_factors
from eqr.features.build import build_features
from tests.conftest import make_synthetic_market


def _good(symbol="S05", as_of="2022-04-19"):
    return {
        "symbol": symbol, "as_of": as_of, "thesis": "A" * 100, "rating": "BUY", "confidence": 0.6, "horizon_months": 12,
        "bull_case": [{"claim": "Sales grew steadily across the last eight quarters.", "citations": ["table:statements"]}],
        "bear_case": [{"claim": "Valuation is above peers on P/E.", "citations": ["table:peers"]}],
        "assessments": {k: {"score": 3, "summary": "Reasonable on the visible numbers.", "citations": ["table:features"]}
                        for k in ("quality", "valuation", "momentum", "governance")},
        "red_flags": [], "catalysts": [{"event": "Q2 results", "expected_by": "2022-11-14", "direction": "either", "citations": ["table:results_calendar"]}],
        "what_would_change_my_mind": ["A drop in promoter holding."], "data_gaps": ["No concall transcript stored."],
        "citations_used": ["table:statements", "table:peers", "table:features"],
    }


def test_schema_accepts_good_and_rejects_uncited_or_unknown():
    assert validate_dossier(_good(), set()) == []
    bad = _good(); bad["bull_case"][0]["citations"] = []
    assert any("citations" in e for e in validate_dossier(bad, set()))
    bad2 = _good(); bad2["bear_case"][0]["citations"] = ["doc:NOPE-123"]
    assert any("unknown citations" in e for e in validate_dossier(bad2, set()))
    ok_doc = _good(); ok_doc["bear_case"][0]["citations"] = ["doc:S05-abc123#p4"]
    assert validate_dossier(ok_doc, {"S05-abc123"}) == []
    bad3 = _good(); bad3["rating"] = "MOON"
    assert validate_dossier(bad3, set())


def test_pack_and_dossier_roundtrip(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    syms, days = make_synthetic_market(tmp_db, n_symbols=12, n_days=500)
    refresh_factors(tmp_db)
    as_of = days[-1].date()
    build_features(tmp_db, as_of, min_turnover_inr=1.0)
    pack = build_pack(tmp_db, "S05", as_of)
    assert pack["features"] and pack["quarterly"] and pack["annual"] and pack["shareholding"]
    assert len(pack["peers"]) >= 1
    dry = run_dossier(tmp_db, "S05", as_of, dry_run=True)
    assert dry["status"] == "DRY_RUN" and dry["prompt_chars"] > 1000
    good = _good("S05", str(as_of))
    out = run_dossier(tmp_db, "S05", as_of, response_text="Here you go:\n" + json.dumps(good))
    assert out["status"] == "STORED"
    row = tmp_db.execute("SELECT rating, confidence FROM dossiers_current WHERE symbol = 'S05'").fetchone()
    assert row == ("BUY", 0.6)
    bad = run_dossier(tmp_db, "S05", as_of, response_text=json.dumps(dict(good, rating="MOON")))
    assert bad["status"] == "REJECTED"
    md = render_markdown(good)
    assert "## Thesis" in md and "table:peers" in md
    assert _extract_json("noise {\"a\": 1} tail") == {"a": 1}


def test_dossier_storage_keys_on_run_id_and_keeps_rejected_runs(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    syms, days = make_synthetic_market(tmp_db, n_symbols=12, n_days=500)
    refresh_factors(tmp_db)
    as_of = days[-1].date()
    build_features(tmp_db, as_of, min_turnover_inr=1.0)
    good = _good("S05", str(as_of))
    out = run_dossier(tmp_db, "S05", as_of, response_text="ok\n" + json.dumps(good))
    assert out["status"] == "STORED" and out["run_id"]
    bad = run_dossier(tmp_db, "S05", as_of, response_text=json.dumps(dict(good, rating="MOON")))
    assert bad["status"] == "REJECTED" and bad["run_id"] != out["run_id"]
    counts = dict(tmp_db.execute("SELECT status, count(*) FROM dossiers WHERE symbol = 'S05' GROUP BY status").fetchall())
    assert counts == {"STORED": 1, "REJECTED": 1}
    assert tmp_db.execute("SELECT rating, confidence FROM dossiers_current WHERE symbol = 'S05'").fetchall() == [("BUY", 0.6)]
    assert tmp_db.execute("SELECT errors_json FROM dossiers WHERE run_id = ?", [bad["run_id"]]).fetchone()[0]
