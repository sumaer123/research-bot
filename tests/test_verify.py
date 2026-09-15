"""T7: the deterministic web-claim verifier (fresh context: pure code over (obj, texts), never
the LLM). A web claim survives only if its verbatim quote is an exact or >=0.90 fuzzy substring of
its cited source text; unsupported claims are struck and moved to data_gaps."""
from eqr.research.verify import (
    normalise, quote_supported, verify_web_claims, web_claim_rows, REJECT_STRUCK_SHARE,
)

TEXT = "Kirloskar Oil Engines registers 16% YoY revenue growth in Q1 FY27; net profit rose."


def test_normalise_collapses_whitespace_and_case():
    assert normalise("  Foo   BAR\n baz ") == "foo bar baz"


def test_exact_fuzzy_and_paraphrase():
    ok, score, method = quote_supported("registers 16% YoY revenue growth in Q1 FY27", TEXT)
    assert ok and method == "exact" and score == 1.0
    ok, score, method = quote_supported("registers 16% YoY revenue growth in Q1 FY 27", TEXT)  # extra space
    assert ok and score >= 0.90 and method in ("exact", "fuzzy")
    ok, score, method = quote_supported("the company grew a lot last quarter", TEXT)
    assert not ok and method == "none"
    ok, score, method = quote_supported("", TEXT)
    assert not ok and method == "empty"


def _obj():
    return {
        "bull_case": [
            {"claim": "Revenue grew 16% YoY in Q1 FY27.",
             "quote": "registers 16% YoY revenue growth in Q1 FY27", "citations": ["web:S-w1"]},
            {"claim": "The order book has doubled to a record.",
             "quote": "order book doubled to a record high", "citations": ["web:S-w2"]},
        ],
        "bear_case": [{"claim": "Valuation is rich vs peers.", "citations": ["table:peers"]}],
        "red_flags": [],
        "catalysts": [],
        "assessments": {k: {"score": 3, "summary": "Reasonable on visible numbers.",
                            "citations": ["table:features"]}
                        for k in ("quality", "valuation", "momentum", "governance")},
        "data_gaps": [],
    }


def test_web_claim_rows_finds_the_web_claims():
    rows = web_claim_rows(_obj())
    web = [r for r in rows if r["web_ids"]]
    assert len(web) == 2 and {r["section"] for r in web} == {"bull_case"}


def test_verify_strikes_unsupported_moves_to_data_gaps():
    texts = {"S-w1": TEXT, "S-w2": "The management commented on domestic demand trends."}  # no support for w2
    pruned, rows, n_web, n_struck = verify_web_claims(_obj(), texts)
    assert n_web == 2 and n_struck == 1
    claims = [c["claim"] for c in pruned["bull_case"]]
    assert claims == ["Revenue grew 16% YoY in Q1 FY27."]                 # unsupported one removed
    assert any("struck" in g.lower() for g in pruned["data_gaps"])
    # the verified web row is real; doc/table rows are 'unverified'
    verified_web = [r for r in rows if r["verify_method"] in ("exact", "fuzzy") and r["verified"]]
    assert len(verified_web) == 1
    assert all(r["verify_method"] == "unverified" for r in rows if r["section"].startswith("assessment"))
    # reject gate: 1/2 = 0.5 > threshold
    assert n_struck / n_web > REJECT_STRUCK_SHARE


def test_all_supported_keeps_everything():
    texts = {"S-w1": TEXT, "S-w2": "the order book doubled to a record high this year"}
    pruned, rows, n_web, n_struck = verify_web_claims(_obj(), texts)
    assert n_web == 2 and n_struck == 0 and len(pruned["bull_case"]) == 2


def test_threshold_value():
    assert REJECT_STRUCK_SHARE == 0.25
