"""Anonymous Parallel Search MCP client (no key, no charge) + read-only CLI balance visibility.

Transport: JSON-RPC over HTTP POST. `initialize` returns the session id in the `mcp-session-id`
response header, which every later call echoes back in `Mcp-Session-Id`. Responses arrive as plain
JSON or as an SSE `event:/data:` stream; both are parsed.

Fail-soft, like surfaces/advisor_client.py: any transport error, non-200, JSON-RPC error or
`isError` result yields None. The client NEVER raises. A per-run call cap and a shared rate limiter
keep the anonymous endpoint (and the frozen $19.86 credit, which the app never touches) safe."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests


@dataclass
class SearchResult:
    url: str
    title: Optional[str]
    publish_date: Optional[str]
    excerpts: list[str] = field(default_factory=list)


class RateLimiter:
    """Enforce a minimum spacing between calls across threads. Injectable clock/sleep for tests."""

    def __init__(self, min_interval_s: float = 1.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.min_interval_s = float(min_interval_s)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last = 0.0
        self._primed = False

    def wait(self) -> None:
        with self._lock:
            if not self._primed:
                self._primed = True
                self._last = self._clock()
                return
            gap = self._clock() - self._last
            if gap < self.min_interval_s:
                self._sleep(self.min_interval_s - gap)
            self._last = self._clock()


def _parse_body(text: str, content_type: str) -> Optional[dict]:
    """A JSON-RPC response, whether plain JSON or an SSE `data:` stream."""
    if not text:
        return None
    is_sse = "text/event-stream" in (content_type or "") or text.lstrip().startswith("event:") \
        or text.lstrip().startswith("data:")
    if is_sse:
        last = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload and payload != "[DONE]":
                    try:
                        last = json.loads(payload)
                    except json.JSONDecodeError:
                        pass
        return last
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _structured_results(rpc: Optional[dict]) -> Optional[list]:
    """The tools/call result's structuredContent.results, or None on error / wrong shape."""
    if not rpc or rpc.get("error"):
        return None
    result = rpc.get("result")
    if not isinstance(result, dict) or result.get("isError"):
        return None
    sc = result.get("structuredContent")
    if not isinstance(sc, dict):
        return None
    results = sc.get("results")
    return results if isinstance(results, list) else None


def parse_search(rpc: Optional[dict]) -> Optional[list[SearchResult]]:
    results = _structured_results(rpc)
    if results is None:
        return None
    out = []
    for r in results:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        ex = [e for e in (r.get("excerpts") or []) if isinstance(e, str)]
        out.append(SearchResult(url=r["url"], title=r.get("title"),
                                publish_date=r.get("publish_date"), excerpts=ex))
    return out


def parse_fetch(rpc: Optional[dict]) -> Optional[dict[str, str]]:
    results = _structured_results(rpc)
    if not results:                       # None or empty -> nothing usable
        return None
    out: dict[str, str] = {}
    for r in results:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        text = r.get("full_content")
        if not text:
            text = "\n\n".join(e for e in (r.get("excerpts") or []) if isinstance(e, str))
        out[r["url"]] = text or ""
    return out or None


class McpClient:
    def __init__(self, url: str, timeout_s: float = 30.0, max_calls: int = 8,
                 limiter: Optional[RateLimiter] = None):
        self.url = url
        self.timeout_s = timeout_s
        self.max_calls = max_calls
        self.limiter = limiter or RateLimiter(1.0)
        self.session_id: Optional[str] = None
        self.calls_made = 0

    def _post(self, method: str, params: Optional[dict] = None) -> Optional[requests.Response]:
        body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method}
        if params is not None:
            body["params"] = params
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            self.limiter.wait()
            return requests.post(self.url, headers=headers, data=json.dumps(body), timeout=self.timeout_s)
        except requests.RequestException:
            return None

    def _rpc(self, method: str, params: Optional[dict] = None) -> Optional[dict]:
        r = self._post(method, params)
        if r is None or r.status_code != 200:
            return None
        return _parse_body(r.text, r.headers.get("content-type", ""))

    def initialize(self) -> bool:
        r = self._post("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "eqr", "version": "1.0"}})
        if r is None or r.status_code != 200:
            return False
        sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        # best-effort per the MCP lifecycle; a notification has no response we care about
        self._post("notifications/initialized")
        return True

    def _reserve(self) -> bool:
        if self.calls_made >= self.max_calls:
            return False
        self.calls_made += 1
        return True

    def web_search(self, objective: str, queries: list[str]) -> Optional[list[SearchResult]]:
        if not self._reserve():
            return None
        rpc = self._rpc("tools/call", {"name": "web_search",
                                       "arguments": {"objective": objective, "search_queries": queries}})
        return parse_search(rpc)

    def web_fetch(self, urls: list[str], objective: Optional[str] = None,
                  full_content: bool = False) -> Optional[dict[str, str]]:
        if not urls or not self._reserve():
            return None
        args: dict = {"urls": urls[:20]}
        if objective:
            args["objective"] = objective
        if full_content:
            args["full_content"] = True
        rpc = self._rpc("tools/call", {"name": "web_fetch", "arguments": args})
        return parse_fetch(rpc)


# --- read-only CLI visibility (allow-listed to `balance get` / `auth`; never a paid channel) ---

def cli_path() -> Optional[str]:
    return shutil.which("parallel-cli") or shutil.which("parallel")


_BALANCE_RX = re.compile(r"balance[^$]*\$\s*([0-9]+(?:\.[0-9]+)?)", re.I)


def _parse_balance_usd(text: str) -> Optional[float]:
    m = _BALANCE_RX.search(text or "")
    return float(m.group(1)) if m else None


def cli_balance_usd() -> Optional[float]:
    """Parse `parallel-cli balance get` (no --json flag). Read-only; None if the CLI is absent."""
    exe = cli_path()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "balance", "get"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return _parse_balance_usd(r.stdout)
