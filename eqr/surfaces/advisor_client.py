"""Reference client for the advisor API — the code Project Upstox would copy (phase R6).

Fail-soft contract: any transport error, non-200, STALE or UNKNOWN status yields
evidence=None, which the caller must treat as an UNKNOWN check (no points, no gate).
The client never raises."""
from __future__ import annotations

from typing import Optional

import requests


def fetch_evidence(base_url: str, token: str, symbol: str, timeout: float = 3.0) -> Optional[dict]:
    try:
        r = requests.get(f"{base_url.rstrip('/')}/advisor/v1/evidence/{symbol.upper()}",
                         headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        if r.status_code != 200:
            return None
        j = r.json()
        return j if j.get("status") == "OK" else None
    except (requests.RequestException, ValueError):
        return None


def evidence_line(ev: Optional[dict], max_points: float = 3.0) -> dict:
    """Turn evidence into ONE conviction-style check. Points only from a VALIDATED
    sleeve's percentile; flags reduce to zero but never block (the caller's gates do that)."""
    if not ev:
        return {"name": "eqr_rank", "status": "UNKNOWN", "points": 0.0, "max_points": max_points,
                "detail": "research bot unavailable"}
    best = None
    for sl in ("sleeve_L", "sleeve_S"):
        s = ev.get(sl) or {}
        if s.get("validated") and s.get("percentile") is not None:
            if best is None or s["percentile"] > best[1]:
                best = (sl, s["percentile"], s.get("rank"), s.get("universe_size"))
    if best is None:
        return {"name": "eqr_rank", "status": "UNKNOWN", "points": 0.0, "max_points": max_points,
                "detail": "no validated sleeve"}
    pts = round(max_points * max(0.0, (best[1] - 0.5) / 0.5), 2)      # top half earns, top decile ~full
    if ev.get("flags"):
        pts = 0.0
    status = "PASS" if pts >= max_points * 0.7 else ("PARTIAL" if pts > 0 else "FAIL")
    return {"name": "eqr_rank", "status": status, "points": pts, "max_points": max_points,
            "detail": f"{best[0]} rank {best[2]}/{best[3]} (pct {best[1]:.0%}); flags {ev.get('flags') or 'none'}; "
                      f"regime {(ev.get('regime') or {}).get('label')}"}
