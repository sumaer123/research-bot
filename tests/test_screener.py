from datetime import date, datetime

from eqr.spine import screener as sc
from eqr.store import query
from tests.conftest import FIXTURES

HTML = (FIXTURES / "screener_reliance_consolidated.html").read_text()


def test_parse_page_sections():
    p = sc.parse_page(HTML)
    assert p.name.startswith("Reliance Industries")
    assert p.industry == "Petroleum Products" and p.sector.startswith("Oil, Gas")
    stmts = {s["stmt"] for s in p.statements}
    assert {"pl_q", "pl_a", "bs_a", "cf_a", "ratios_a"} <= stmts
    q = [s for s in p.statements if s["stmt"] == "pl_q" and s["line_item"] == "sales"]
    assert len(q) >= 12 and all(isinstance(s["period_end"], date) for s in q)
    a = {(s["period_end"], s["line_item"]): s["value"] for s in p.statements if s["stmt"] == "pl_a"}
    assert a[(date(2019, 3, 31), "sales")] == 568337
    assert a[(date(2019, 3, 31), "eps_in_rs")] == 29.28
    bs = {(s["period_end"], s["line_item"]): s["value"] for s in p.statements if s["stmt"] == "bs_a"}
    assert bs[(date(2019, 3, 31), "equity_capital")] == 5926
    sh = [s for s in p.shareholding if s["holder"] == "promoters"]
    assert sh and 40 < sh[-1]["pct"] < 60
    assert p.meta.get("market_cap_cr", 0) > 1e5
    assert p.result_pdfs and p.result_pdfs[0][1].startswith("http")


def test_line_key():
    assert sc.line_key("Sales&nbsp; +") == "sales"
    assert sc.line_key("OPM %") == "opm_pct"
    assert sc.line_key("Cash from Operating Activity +") == "cash_from_operating_activity"


def test_visible_from_rules():
    assert sc.visible_from_for(date(2026, 6, 30), "pl_q", None) == date(2026, 8, 14)
    assert sc.visible_from_for(date(2026, 3, 31), "pl_q", None) == date(2026, 5, 30)
    assert sc.visible_from_for(date(2026, 3, 31), "pl_a", date(2026, 4, 25)) == date(2026, 4, 25)


def test_load_parsed_first_seen_wins_and_revisions(tmp_db):
    p = sc.parse_page(HTML)
    out = sc.load_parsed(tmp_db, "RELIANCE", "consolidated", p, datetime(2026, 9, 14, 1, 0))
    assert out["statements_new"] > 100 and out["revisions"] == 0
    # a restated value later: original stays, revision recorded
    for s in p.statements:
        if s["stmt"] == "pl_a" and s["period_end"] == date(2019, 3, 31) and s["line_item"] == "sales":
            s["value"] = 999999
    out2 = sc.load_parsed(tmp_db, "RELIANCE", "consolidated", p, datetime(2026, 9, 15, 1, 0))
    assert out2["revisions"] == 1
    v = query(tmp_db, "SELECT value FROM statements WHERE symbol='RELIANCE' AND stmt='pl_a' "
                      "AND period_end='2019-03-31' AND line_item='sales'").iloc[0, 0]
    assert v == 568337
    ind = query(tmp_db, "SELECT industry FROM screener_meta WHERE symbol='RELIANCE'").iloc[0, 0]
    assert ind == "Petroleum Products"
