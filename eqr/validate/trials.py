"""Append-only trial ledger (registry-lite).

The deflated Sharpe is only honest if it counts every configuration ever evaluated for a
sleeve, not just one run's grid. Each `eqr backtest` / `eqr validate` invocation appends one
JSON line here; `prior_distinct_trials` gives the count of distinct configs tried in earlier
runs so a new validation can pass `len(grid) + prior_distinct_trials(...)` as n_trials.

The ledger lives at experiments/trials-<sleeve>.jsonl (tracked in git); the directory can be
redirected with EQR_EXPERIMENTS_DIR for tests. Re-running the identical grid is not new
multiple testing, so the count is the size of the union of distinct trial keys, not the number
of invocations.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from ..config import PROJECT_ROOT, settings


def experiments_dir() -> Path:
    d = Path(os.environ.get("EQR_EXPERIMENTS_DIR", str(PROJECT_ROOT / "experiments"))).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path(sleeve: str) -> Path:
    return experiments_dir() / f"trials-{sleeve}.jsonl"


def read_trials(sleeve: str) -> list[dict]:
    p = ledger_path(sleeve)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def distinct_keys(sleeve: str) -> set[str]:
    keys: set[str] = set()
    for t in read_trials(sleeve):
        keys.update(t.get("grid", []))
    return keys


def prior_distinct_trials(sleeve: str, exclude: Optional[Iterable[str]] = None) -> int:
    """Distinct trial keys recorded for `sleeve`, minus any in `exclude` (the current grid)."""
    return len(distinct_keys(sleeve) - set(exclude or []))


def code_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT),
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:                                                          # noqa: BLE001
        return ""


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:                                                          # noqa: BLE001
        return ""


def append_trial(entry: dict, sleeve: str) -> Path:
    p = ledger_path(sleeve)
    with p.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return p


def _entry_from_wf(wf: dict, run_id: str, purpose: str, report_path: Optional[Path]) -> dict:
    return {
        "ts": datetime.now().isoformat(timespec="seconds"), "sleeve": wf.get("sleeve"), "purpose": purpose,
        "run_id": run_id, "grid": wf.get("grid", []), "n_grid": len(wf.get("grid", [])),
        "costs": wf.get("costs"), "rf_annual": wf.get("rf_annual"), "benchmark": "Nifty 500",
        "embargo_days": wf.get("embargo_days"), "purge_sessions": wf.get("purge_sessions"),
        "holdout_start": wf.get("holdout_start"), "start": wf.get("start"), "end": wf.get("end"),
        "code_commit": code_commit(),
        "report_path": str(report_path) if report_path else None,
        "report_sha256": _sha256(Path(report_path) / "report.md") if report_path else "",
    }


def log_walkforward(wf: dict, run_id: str, purpose: str = "protocol",
                    report_path: Optional[Path] = None) -> Path:
    return append_trial(_entry_from_wf(wf, run_id, purpose, report_path), wf.get("sleeve"))


def log_backtest(cfg: dict, run_id: str, purpose: str = "exploratory",
                 report_path: Optional[Path] = None) -> Path:
    """A single backtest is a one-config trial; derive its grid key from the config."""
    sl = cfg.get("sleeve", {})
    key = _key_from_config(sl)
    wf = {"sleeve": sl.get("name"), "grid": [key], "costs": cfg.get("costs"), "rf_annual": cfg.get("rf_annual"),
          "start": cfg.get("start"), "end": cfg.get("end")}
    return append_trial(_entry_from_wf(wf, run_id, purpose, report_path), sl.get("name"))


def _key_from_config(sl: dict) -> str:
    return (f"{sl.get('name')}-N{sl.get('top_n')}-{sl.get('variant')}-"
            f"T{int((sl.get('min_turnover_inr') or 1e7) / 1e7)}cr")


def seed_from_reports(reports_dir: Optional[Path] = None, purpose: str = "repair") -> dict:
    """One-time backfill: read every report under reports_dir and append a ledger line per run,
    deduped by report_path. Returns {sleeve: n_added}."""
    reports_dir = Path(reports_dir) if reports_dir else settings().reports_dir
    seen = {s: {t.get("report_path") for t in read_trials(s)} for s in ("L", "S")}
    added = {"L": 0, "S": 0}
    if not reports_dir.exists():
        return added
    for d in sorted(reports_dir.glob("*")):
        wj, rj = d / "walkforward.json", d / "report.json"
        if wj.exists():
            wf = json.loads(wj.read_text())
            sleeve = wf.get("sleeve")
            entry = _entry_from_wf(wf, d.name, purpose, d)
        elif rj.exists():
            cfg = json.loads(rj.read_text()).get("config", {})
            sl = cfg.get("sleeve", {})
            sleeve = sl.get("name")
            entry = _entry_from_wf(
                {"sleeve": sleeve, "grid": [_key_from_config(sl)], "costs": cfg.get("costs"),
                 "rf_annual": cfg.get("rf_annual"), "start": cfg.get("start"), "end": cfg.get("end")},
                d.name, purpose, d)
        else:
            continue
        if sleeve not in ("L", "S") or str(d) in seen[sleeve]:
            continue
        append_trial(entry, sleeve)
        seen[sleeve].add(str(d))
        added[sleeve] += 1
    return added
