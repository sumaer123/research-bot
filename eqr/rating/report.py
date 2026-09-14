"""Calibration report (markdown + json + csv) under data/reports/<run_id>/."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import settings


def _fmt(v, pct=False, nd=3):
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int,)):
        return str(v)
    if pct:
        return f"{v * 100:.1f}%"
    return f"{v:.{nd}f}"


def write_calibration_report(out: dict, hist: pd.DataFrame) -> Path:
    d = settings().reports_dir / out["run_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "calibration.json").write_text(json.dumps(out, indent=1, default=str))
    hist.to_csv(d / "history.csv", index=False)
    m, acc = out.get("metrics", {}), out.get("acceptance", {})
    md = [f"# Rating engine calibration — {out['engine_version']} — {out['verdict']}", "",
          f"run {out['run_id']} · signal dates {out['start']} → {out['end']} · holdout from {out['holdout_start']} · "
          f"trials {out['n_trials']} · {out.get('n_history_rows', 0)} history rows · {out.get('elapsed_s')}s", "",
          f"_{out.get('note', '')}_", "",
          "## Acceptance bar", "", "| Check | Value | Threshold | Pass |", "|---|---|---|---|"]
    for k, v in acc.items():
        if not isinstance(v, dict):
            continue
        p = v.get("pass")
        md.append(f"| {k} | {_fmt(v.get('value'))} | {v.get('threshold')} | {'PASS' if p else ('FAIL' if p is False else 'not evaluable')} |")
    md += ["", f"**{acc.get('n_pass', 0)} pass · {acc.get('n_fail', 0)} fail · {acc.get('n_not_evaluable', 0)} not evaluable → {out['verdict']}**", ""]
    md += ["## Tier statistics (out-of-sample folds)", "", "| Verdict | n | mean 12m excess | hit rate |", "|---|---|---|---|"]
    for t, s in (m.get("tier_stats") or {}).items():
        md.append(f"| {t} | {s['n']} | {_fmt(s['mean_excess'], pct=True)} | {_fmt(s['hit'], pct=True)} |")
    if m.get("holdout_tier_stats"):
        md += ["", "## Holdout (evaluated once)", "", "| Verdict | n | mean 12m excess |", "|---|---|---|"]
        for t, s in m["holdout_tier_stats"].items():
            md.append(f"| {t} | {s['n']} | {_fmt(s['mean_excess'], pct=True)} |")
        md.append(f"\nholdout long-short: {_fmt(m.get('holdout_long_short'), pct=True)} · selected variant {out.get('holdout_selected')}")
    md += ["", "## Folds", "", "| Year | Selected | Train IC by variant | n train | n test |", "|---|---|---|---|---|"]
    for f in out.get("folds", []):
        md.append(f"| {f['year']} | {f['selected']} | " + ", ".join(f"{k} {_fmt(v)}" for k, v in f['train_ic'].items()) + f" | {f['n_train']} | {f['n_test']} |")
    md += ["", "## Variant diagnostics (full pre-holdout period, incl. the no_valuation double-count check)", "",
           "| Variant | mean IC | IC s.e. | long-short pp/yr |", "|---|---|---|---|"]
    for v, s in (out.get("variant_diagnostics") or {}).items():
        md.append(f"| {v} | {_fmt(s.get('ic_mean'))} | {_fmt(s.get('ic_se'))} | {_fmt(s.get('long_short_pp'), pct=True)} |")
    md += ["", "## Tier shares (mean across dates)", "", "| Verdict | share |", "|---|---|"]
    for t, s in (m.get("tier_shares") or {}).items():
        md.append(f"| {t} | {_fmt(s, pct=True)} |")
    md += ["", f"IC HIGH-DCI cohort {_fmt(m.get('ic_high_dci'))} · LOW-DCI cohort {_fmt(m.get('ic_low_dci'))} · "
           f"score/coverage corr {_fmt(m.get('score_coverage_corr'))} · monthly transition {_fmt(m.get('monthly_transition'), pct=True)}", ""]
    md += ["## Caveats", "", "- fundamentals are as-restated screener aggregates (AS_RESTATED_FUNDAMENTALS)",
           "- benchmark is NIFTY 500 + 1.3%/yr TR proxy (BENCH_PROXY)",
           "- event-driven flags (pledge, insider, rating, audit, surveillance) are forward-only (CONTROLS_NO_HISTORY): excluded from the flag-precision check",
           "- a VALIDATED verdict here places the engine at PROVISIONAL on the claim ladder, never higher"]
    (d / "report.md").write_text("\n".join(md))
    return d / "report.md"
