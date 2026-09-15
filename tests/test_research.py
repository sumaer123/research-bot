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


def test_web_citation_requires_allowed_id_and_quote():
    d = _good()
    d["bull_case"].append({"claim": "Q1 revenue grew 16% YoY per recent press coverage.",
                           "citations": ["web:KIRLOSENG-wabc1234de"]})
    # web id not in allowed_web -> unknown citation
    assert any("unknown citations" in e for e in validate_dossier(d, set(), allowed_web=frozenset()))
    # allowed id but no verbatim quote -> rejected
    allowed = frozenset({"KIRLOSENG-wabc1234de"})
    assert any("without a verbatim quote" in e for e in validate_dossier(d, set(), allowed_web=allowed))
    # allowed id + quote -> valid
    d["bull_case"][-1]["quote"] = "registers 16% YoY revenue growth in Q1 FY27"
    assert validate_dossier(d, set(), allowed_web=allowed) == []


def test_v1_dossier_without_web_is_still_valid():
    assert validate_dossier(_good(), set()) == []
    assert validate_dossier(_good(), set(), allowed_web=frozenset()) == []


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


def _prep(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    syms, days = make_synthetic_market(tmp_db, n_symbols=12, n_days=500)
    refresh_factors(tmp_db)
    as_of = days[-1].date()
    build_features(tmp_db, as_of, min_turnover_inr=1.0)
    return as_of


def _seed_web_source(tmp_db, symbol, src_id, text, as_of):
    from datetime import datetime, timedelta
    from eqr.config import settings
    rel = f"{symbol}/{src_id}.txt"
    p = settings().web_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    tmp_db.execute(
        "INSERT INTO web_sources (src_id, symbol, run_id, url, title, published, source_kind, sha256, "
        "text_path, fetched_at, as_of, visible_from, facet) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [src_id, symbol, "seed", f"https://moneycontrol.com/{src_id}", "Q1 press", as_of - timedelta(days=20),
         "parallel_mcp_fetch", "sha", rel, datetime.now(), as_of, as_of - timedelta(days=5), "results"])


def test_web_dossier_stores_verified_claims_and_run_row(tmp_db, monkeypatch, tmp_path):
    as_of = _prep(tmp_db, tmp_path, monkeypatch)
    # parallel is OFF (tmp_db fixture) so the auto-web step is a DISABLED no-op; we pre-seed the source.
    _seed_web_source(tmp_db, "S05", "S05-wq1",
                     "Kirloskar registers 16% YoY revenue growth in Q1 FY27 with a record order book.", as_of)
    good = _good("S05", str(as_of))
    good["bull_case"].append({"claim": "Revenue grew 16% YoY in the latest quarter.",
                              "quote": "registers 16% YoY revenue growth in Q1 FY27",
                              "citations": ["web:S05-wq1"]})
    out = run_dossier(tmp_db, "S05", as_of, response_text="ok\n" + json.dumps(good), web=True)
    assert out["status"] == "STORED" and out["web_claims"] == 1 and out["struck"] == 0
    assert out["webresearch"] == "DISABLED"                       # auto-web off in tests; seeded source used
    verified = tmp_db.execute(
        "SELECT count(*) FROM dossier_claims WHERE run_id=? AND verified=true", [out["run_id"]]).fetchone()[0]
    assert verified == 1
    mode, status = tmp_db.execute("SELECT mode, status FROM research_runs WHERE run_id=?",
                                  [out["run_id"]]).fetchone()
    assert mode == "dossier_web" and status == "STORED"
    # the anchor: the stored quote is a verbatim substring of the source text on disk
    from eqr.config import settings
    txt = (settings().web_dir / "S05" / "S05-wq1.txt").read_text()
    assert "registers 16% YoY revenue growth in Q1 FY27" in txt


def test_web_dossier_rejects_when_quote_unsupported(tmp_db, monkeypatch, tmp_path):
    as_of = _prep(tmp_db, tmp_path, monkeypatch)
    _seed_web_source(tmp_db, "S05", "S05-wq1", "The management discussed domestic demand trends only.", as_of)
    good = _good("S05", str(as_of))
    good["bull_case"] = [{"claim": "Revenue reportedly grew 40% YoY, a blowout quarter.",
                          "quote": "revenue grew 40% YoY a blowout quarter",     # not in the source text
                          "citations": ["web:S05-wq1"]}]
    out = run_dossier(tmp_db, "S05", as_of, response_text=json.dumps(good), web=True)
    assert out["status"] == "REJECTED"                            # 1/1 web quotes unsupported > 25%


def test_no_web_behaves_as_v1(tmp_db, monkeypatch, tmp_path):
    as_of = _prep(tmp_db, tmp_path, monkeypatch)
    out = run_dossier(tmp_db, "S05", as_of, response_text=json.dumps(_good("S05", str(as_of))), web=False)
    assert out["status"] == "STORED"
    assert tmp_db.execute("SELECT count(*) FROM dossier_claims").fetchone()[0] == 0
    assert tmp_db.execute("SELECT count(*) FROM research_runs").fetchone()[0] == 0


def test_web_dossier_still_stores_when_webresearch_unavailable(tmp_db, monkeypatch, tmp_path):
    as_of = _prep(tmp_db, tmp_path, monkeypatch)      # no seeded web sources; parallel OFF -> DISABLED
    out = run_dossier(tmp_db, "S05", as_of, response_text=json.dumps(_good("S05", str(as_of))), web=True)
    assert out["status"] == "STORED" and out["webresearch"] == "DISABLED" and out["web_claims"] == 0


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
