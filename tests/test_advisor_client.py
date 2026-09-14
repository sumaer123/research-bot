from eqr.surfaces.advisor_client import evidence_line, fetch_evidence


def test_evidence_line_fail_soft_and_scoring():
    assert evidence_line(None)["status"] == "UNKNOWN"
    ev = {"status": "OK", "flags": [], "regime": {"label": "RISK_ON"},
          "sleeve_L": {"validated": True, "percentile": 0.95, "rank": 10, "universe_size": 200},
          "sleeve_S": {"validated": False, "percentile": 0.99, "rank": 1, "universe_size": 100}}
    line = evidence_line(ev)
    assert line["status"] == "PASS" and line["points"] == 2.7 and "sleeve_L" in line["detail"]
    ev["flags"] = ["GSM"]
    assert evidence_line(ev)["points"] == 0.0
    ev["sleeve_L"]["validated"] = False
    assert evidence_line(ev)["status"] == "UNKNOWN"
    assert fetch_evidence("http://127.0.0.1:1", "x", "RELIANCE", timeout=0.2) is None
