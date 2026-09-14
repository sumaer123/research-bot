"""Polite HTTP: one session, per-host rate limit, bounded retries, immutable raw archive.

Every call returns a FetchResult; nothing here raises past the caller except
programming errors. NSE's cookie-gated /api endpoints get a warm-up GET on the
homepage first (the 403 it returns still sets the cookies)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from ..config import UA, settings

NSE_HOME = "https://www.nseindia.com"
RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    source: str
    key: str
    status: str                      # ok | cached | missing | blocked | error
    http_status: Optional[int] = None
    bytes: int = 0
    path: Optional[Path] = None
    error: str = ""
    content: Optional[bytes] = None
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "cached")

    def text(self, encoding: str = "utf-8") -> str:
        return (self.content or b"").decode(encoding, errors="replace")

    def log_row(self, run_id: str) -> dict:
        return {"run_id": run_id, "source": self.source, "key": self.key, "status": self.status,
                "http_status": self.http_status, "bytes": self.bytes,
                "started_at": self.started_at, "ended_at": self.ended_at or datetime.now(),
                "error": self.error[:500]}


class Http:
    def __init__(self, rate_limit_s: Optional[float] = None, proxy: Optional[str] = None,
                 raw_dir: Optional[Path] = None, timeout: int = 30, max_retries: int = 3):
        s = settings()
        self.rate_limit_s = s.rate_limit_s if rate_limit_s is None else rate_limit_s
        self.raw_dir = raw_dir or s.raw_dir
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        proxy = s.proxy if proxy is None else proxy
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self._last_call: dict[str, float] = {}

    # ---------------------------------------------------------------- core --
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_call.get(host, 0.0)
        wait = self.rate_limit_s - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_call[host] = time.monotonic()

    def get(self, url: str, *, source: str, key: str, raw_rel: Optional[str] = None,
            headers: Optional[dict] = None, params: Optional[dict] = None,
            allow_cached: bool = True) -> FetchResult:
        res = FetchResult(source=source, key=key, status="error")
        if raw_rel and allow_cached:
            p = self.raw_dir / raw_rel
            if p.exists() and p.stat().st_size > 0:
                res.status, res.path, res.content = "cached", p, p.read_bytes()
                res.bytes, res.http_status, res.ended_at = len(res.content), 200, datetime.now()
                return res
        attempt, backoff = 0, 1.0
        while True:
            attempt += 1
            self._throttle(url)
            try:
                r = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                res.error = f"{type(e).__name__}: {e}"
                if attempt <= self.max_retries:
                    time.sleep(backoff); backoff *= 2
                    continue
                res.ended_at = datetime.now()
                return res
            res.http_status = r.status_code
            if r.status_code in RETRY_STATUSES and attempt <= self.max_retries:
                time.sleep(backoff); backoff *= 2
                continue
            if r.status_code == 200:
                res.content, res.bytes, res.status = r.content, len(r.content), "ok"
                if raw_rel:
                    p = self.raw_dir / raw_rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    tmp = p.with_suffix(p.suffix + ".part")
                    tmp.write_bytes(r.content)
                    tmp.replace(p)
                    res.path = p
            elif r.status_code == 404:
                res.status = "missing"
            elif r.status_code in (401, 403):
                res.status, res.error = "blocked", f"HTTP {r.status_code}"
            else:
                res.status, res.error = "error", f"HTTP {r.status_code}"
            res.ended_at = datetime.now()
            return res


class NseApi:
    """Cookie-gated www.nseindia.com/api client with warm-up and one re-warm on 401/403."""

    def __init__(self, http: Optional[Http] = None):
        self.http = http or Http()
        self._warm = False

    def warm(self) -> None:
        self.http._throttle(NSE_HOME)
        try:
            self.http.session.get(NSE_HOME + "/", headers={"Accept": "text/html,application/xhtml+xml"},
                                  timeout=self.http.timeout)
        except requests.RequestException:
            pass
        self._warm = True

    def get_json(self, path: str, params: Optional[dict] = None, *, source: str, key: str):
        """Returns (FetchResult, parsed_json_or_None)."""
        if not self._warm:
            self.warm()
        headers = {"Accept": "application/json, text/plain, */*", "Referer": NSE_HOME + "/"}
        res = self.http.get(NSE_HOME + path, source=source, key=key, headers=headers, params=params)
        if res.status == "blocked":
            self.warm()
            res = self.http.get(NSE_HOME + path, source=source, key=key, headers=headers, params=params)
        if not res.ok:
            return res, None
        try:
            import json
            return res, json.loads(res.text())
        except ValueError as e:
            res.status, res.error = "error", f"bad json: {e}"
            return res, None

    def get_bytes(self, url: str, *, source: str, key: str, raw_rel: Optional[str] = None) -> FetchResult:
        if not self._warm:
            self.warm()
        headers = {"Accept": "*/*", "Referer": NSE_HOME + "/"}
        return self.http.get(url, source=source, key=key, headers=headers, raw_rel=raw_rel)
