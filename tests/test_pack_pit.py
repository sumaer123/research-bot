"""The dossier pack is a point-in-time contract: nothing filed, announced or made visible
after the as-of date may appear, and the model's response must be bound to the request."""
import json
from datetime import timedelta

from eqr.features.build import build_features
from eqr.research.pack import build_pack
from eqr.research.dossier import run_dossier
from eqr.spine.adjust import refresh_factors
from tests.conftest import make_synthetic_market
from tests.test_research import _good


def _seed(tmp_db):
    syms, days = make_synthetic_market(tmp_db, n_symbols=12, n_days=500)
    refresh_factors(tmp_db)
    as_of = days[400].date()
    build_features(tmp_db, as_of, min_turnover_inr=1.0)
    return as_of


def test_pack_excludes_post_as_of_filings_announcements_and_documents(tmp_db):
    as_of = _seed(tmp_db)
    # results_calendar: one visible (filed before), one poison (filed after)
    tmp_db.execute("INSERT INTO results_calendar (symbol, period_end, consolidated, filing_dt, audited, period, source) "
                   "VALUES ('S05', ?, 'Consolidated', ?, 'Yes', 'Q', 't'), ('S05', ?, 'Consolidated', ?, 'Yes', 'Q', 't')",
                   [as_of - timedelta(days=120), as_of - timedelta(days=10),
                    as_of + timedelta(days=60), as_of + timedelta(days=70)])
    # an unrelated symbol's filing must never leak into S05's pack
    tmp_db.execute("INSERT INTO results_calendar (symbol, period_end, consolidated, filing_dt, audited, period, source) "
                   "VALUES ('S06', ?, 'Consolidated', ?, 'Yes', 'Q', 't')", [as_of - timedelta(days=30), as_of - timedelta(days=5)])
    # announcements: poison at exactly as_of + 1 day (the old +1-day bug boundary)
    tmp_db.execute("INSERT INTO announcements (symbol, ann_dt, subject) VALUES ('S05', ?, 'visible'), ('S05', ?, 'poison')",
                   [as_of - timedelta(days=5), as_of + timedelta(days=1)])
    # documents: poison visible only from as_of + 1
    tmp_db.execute("INSERT INTO documents (doc_id, symbol, kind, title, period, pages, text_path, visible_from) VALUES "
                   "('D-vis', 'S05', 'results', 't', 'Q', 5, '/nope.txt', ?), ('D-poison', 'S05', 'results', 't', 'Q', 5, '/nope.txt', ?)",
                   [as_of - timedelta(days=30), as_of + timedelta(days=1)])

    pack = build_pack(tmp_db, "S05", as_of)

    filed = [r["filing_dt"] for r in pack["results_calendar"]]
    assert filed and all(str(f)[:10] <= str(as_of) for f in filed)
    ann_subjects = {r["subject"] for r in pack["announcements"]}
    assert "visible" in ann_subjects and "poison" not in ann_subjects
    doc_ids = {d["doc_id"] for d in pack["documents"]}
    assert "D-vis" in doc_ids and "D-poison" not in doc_ids


def test_company_snapshot_is_flagged_not_point_in_time(tmp_db):
    as_of = _seed(tmp_db)
    pack = build_pack(tmp_db, "S05", as_of)
    assert "company" not in pack and "screener_meta" not in pack
    assert pack["company_snapshot_current"]["pit"] is False


def _add_web_source(tmp_db, src_id, symbol, visible_from, text, facet="results", published=None):
    from eqr.config import settings
    from datetime import datetime
    rel = f"{symbol}/{src_id}.txt"
    p = settings().web_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    tmp_db.execute(
        "INSERT INTO web_sources (src_id, symbol, run_id, url, title, published, source_kind, sha256, "
        "text_path, fetched_at, as_of, visible_from, facet) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [src_id, symbol, "r1", f"https://moneycontrol.com/{src_id}", f"title {src_id}", published,
         "parallel_mcp_fetch", "sha", rel, datetime.now(), visible_from, visible_from, facet])


def test_pack_web_section_is_point_in_time(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    as_of = _seed(tmp_db)
    _add_web_source(tmp_db, "S05-wVIS", "S05", as_of - timedelta(days=5),
                    "Kirloskar registers 16% YoY revenue growth in Q1.", published=as_of - timedelta(days=30))
    _add_web_source(tmp_db, "S05-wHID", "S05", as_of + timedelta(days=5), "future news, must be hidden")
    pack = build_pack(tmp_db, "S05", as_of, web=True)
    assert "web" in pack and len(pack["web"]) == 1
    w = pack["web"][0]
    assert w["src_id"] == "S05-wVIS" and w["facet"] == "results" and w["excerpt"] and w["url"]
    assert "web:<src_id>" in pack["citation_rules"]


def test_pack_web_false_is_unchanged(tmp_db):
    as_of = _seed(tmp_db)
    _add_web_source(tmp_db, "S05-wVIS", "S05", as_of - timedelta(days=5), "some text")
    pack = build_pack(tmp_db, "S05", as_of)                    # default web=False
    assert "web" not in pack


def test_pack_web_empty_sets_note(tmp_db):
    as_of = _seed(tmp_db)
    pack = build_pack(tmp_db, "S06", as_of, web=True)          # S06 has no web sources
    assert pack["web"] == [] and "web_note" in pack


def test_dossier_rejects_a_response_bound_to_the_wrong_symbol_or_date(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    as_of = _seed(tmp_db)
    wrong_symbol = run_dossier(tmp_db, "S05", as_of, response_text=json.dumps(_good("S06", str(as_of))))
    assert wrong_symbol["status"] == "REJECTED"
    wrong_date = run_dossier(tmp_db, "S05", as_of, response_text=json.dumps(_good("S05", "2019-01-01")))
    assert wrong_date["status"] == "REJECTED"


def test_dossier_rejects_a_page_citation_beyond_the_document_length(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    as_of = _seed(tmp_db)
    tmp_db.execute("INSERT INTO documents (doc_id, symbol, kind, title, period, pages, text_path, visible_from) "
                   "VALUES ('S05-doc1', 'S05', 'results', 't', 'Q', 3, '/nope.txt', ?)", [as_of - timedelta(days=10)])
    good = _good("S05", str(as_of))
    good["bull_case"][0]["citations"] = ["doc:S05-doc1#p9"]      # doc has only 3 pages
    out = run_dossier(tmp_db, "S05", as_of, response_text=json.dumps(good))
    assert out["status"] == "REJECTED" and any("exceeds" in e for e in out["errors"])
