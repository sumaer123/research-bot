"""T2: MCP transport + pure parsers + rate limiter + call cap + read-only balance parse.
Zero network: requests.post is monkeypatched. A test that forgets to patch and opens a real
socket would be a bug, so the default fake raises on any unmapped method."""
import json
from pathlib import Path

import pytest

import eqr.research.parallel_client as pc
from eqr.research.parallel_client import (
    McpClient, RateLimiter, SearchResult, parse_search, parse_fetch, _parse_balance_usd,
)

FIX = Path(__file__).parent / "fixtures" / "parallel"


def _load(name):
    return json.loads((FIX / name).read_text())


class FakeResp:
    def __init__(self, body, status=200, content_type="application/json", session_id=None):
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.status_code = status
        self.headers = {"content-type": content_type}
        if session_id:
            self.headers["mcp-session-id"] = session_id


class FakePost:
    """Dispatches on the JSON-RPC method in the request body."""
    def __init__(self, mapping, session_id="sess-1", record=None):
        self.mapping = mapping
        self.session_id = session_id
        self.record = record if record is not None else []

    def __call__(self, url, headers=None, data=None, timeout=None):
        body = json.loads(data)
        method = body.get("method")
        self.record.append(method)
        if method == "initialize":
            return FakeResp(_load("initialize.json"), session_id=self.session_id)
        if method == "notifications/initialized":
            return FakeResp("", status=202)
        if method == "tools/call":
            name = body["params"]["name"]
            return self.mapping[name]()
        raise AssertionError(f"unexpected method {method}")


def _init(monkeypatch, mapping, **kw):
    record = []
    monkeypatch.setattr(pc.requests, "post", FakePost(mapping, record=record))
    c = McpClient("https://search.parallel.ai/mcp", limiter=RateLimiter(0.0), **kw)
    assert c.initialize() is True
    return c, record


def test_initialize_captures_session():
    pass  # covered via _init below


def test_web_search_parses_structured_content(monkeypatch):
    mapping = {"web_search": lambda: FakeResp(_load("web_search_results.json"))}
    c, _ = _init(monkeypatch, mapping)
    assert c.session_id == "sess-1"
    out = c.web_search("obj", ["q one two", "q three four"])
    assert isinstance(out, list) and len(out) == 10
    assert all(isinstance(r, SearchResult) for r in out)
    assert out[0].url.startswith("http") and out[0].excerpts


def test_sse_body_is_parsed(monkeypatch):
    raw = _load("web_search_results.json")
    sse = f"event: message\ndata: {json.dumps(raw)}\n\n"
    mapping = {"web_search": lambda: FakeResp(sse, content_type="text/event-stream")}
    c, _ = _init(monkeypatch, mapping)
    out = c.web_search("obj", ["q one two"])
    assert out and len(out) == 10


def test_transport_error_returns_none_never_raises(monkeypatch):
    def boom(*a, **k):
        raise pc.requests.RequestException("no network in tests")
    monkeypatch.setattr(pc.requests, "post", boom)
    c = McpClient("https://x", limiter=RateLimiter(0.0))
    assert c.initialize() is False
    assert c.web_search("o", ["q one two"]) is None
    assert c.web_fetch(["https://x/a"]) is None


def test_non_200_returns_none(monkeypatch):
    mapping = {"web_search": lambda: FakeResp("rate limited", status=429, content_type="text/plain")}
    c, _ = _init(monkeypatch, mapping)
    assert c.web_search("o", ["q one two"]) is None


def test_is_error_response_returns_none(monkeypatch):
    err = {"jsonrpc": "2.0", "id": "1", "result": {"isError": True, "content": [{"type": "text", "text": "boom"}]}}
    mapping = {"web_search": lambda: FakeResp(err)}
    c, _ = _init(monkeypatch, mapping)
    assert c.web_search("o", ["q one two"]) is None


def test_call_cap_refuses_beyond_max(monkeypatch):
    mapping = {"web_search": lambda: FakeResp(_load("web_search_results.json"))}
    c, record = _init(monkeypatch, mapping, max_calls=8)
    for _ in range(8):
        assert c.web_search("o", ["q one two"]) is not None
    assert c.calls_made == 8
    assert c.web_search("o", ["q one two"]) is None      # 9th refused
    assert c.calls_made == 8                              # not incremented, no post made
    assert record.count("tools/call") == 8


def test_web_fetch_maps_url_to_text_full_and_excerpts(monkeypatch):
    mapping = {
        "web_fetch": lambda: FakeResp(_load("web_fetch.json")),
    }
    c, _ = _init(monkeypatch, mapping)
    full = _load("web_fetch.json")["result"]["structuredContent"]["results"][0]
    out = c.web_fetch([full["url"]])
    assert isinstance(out, dict) and full["url"] in out and len(out[full["url"]]) > 0

    # short fixture: no full_content -> excerpts are joined
    mapping2 = {"web_fetch": lambda: FakeResp(_load("web_fetch_short.json"))}
    c2, _ = _init(monkeypatch, mapping2)
    short = _load("web_fetch_short.json")["result"]["structuredContent"]["results"][0]
    out2 = c2.web_fetch([short["url"]])
    assert out2[short["url"]] == "\n\n".join(short["excerpts"])


def test_parse_search_and_fetch_are_pure():
    results = parse_search(_load("web_search_results.json"))
    assert len(results) == 10 and results[0].url
    assert parse_search({"result": {"isError": True}}) is None
    assert parse_search({"error": {"code": -1}}) is None
    fetched = parse_fetch(_load("web_fetch.json"))
    assert isinstance(fetched, dict) and len(fetched) == 1
    assert parse_fetch({"result": {}}) is None


def test_rate_limiter_spaces_calls_with_injected_clock():
    now = [0.0]
    slept = []
    lim = RateLimiter(1.0, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    lim.wait()                     # first call: no wait
    assert slept == []
    now[0] = 0.3                   # 0.3s later
    lim.wait()                     # must sleep ~0.7 to reach 1.0 spacing
    assert slept and abs(slept[0] - 0.7) < 1e-9


def test_balance_parse_from_fixture_and_none_when_cli_missing(monkeypatch):
    assert _parse_balance_usd((FIX / "balance_get.txt").read_text()) == 19.86
    assert _parse_balance_usd("no balance here") is None
    monkeypatch.setattr(pc, "cli_path", lambda: None)
    assert pc.cli_balance_usd() is None
