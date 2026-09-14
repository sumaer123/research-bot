"""Backtest / walk-forward reports: JSON + Markdown + CSVs under data/reports/<run_id>/,
one row in the backtests table."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from ..config import settings
from .backtest import BacktestResult


def _pct(x, digits=1):
    try:
        return f"{x * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _num(x, digits=2):
    try:
        return f"{x:.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def write_backtest_report(con: duckdb.DuckDBPyConnection, res: BacktestResult, run_id: str, title: str) -> Path:
    out = settings().reports_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    res.equity.rename("equity").to_frame().join(res.bench_equity.rename("bench")).to_csv(out / "equity.csv")
    if len(res.trades):
        res.trades.to_csv(out / "trades.csv", index=False)
    (out / "holdings.json").write_text(json.dumps(res.holdings, indent=1, default=str))
    s = res.stats
    md = [f"# {title}", "", f"Run `{run_id}` · {s['start']} → {s['end']} · capital ₹{res.config['capital']:,.0f}", "",
          "| Metric | Strategy | NIFTY 500 TR proxy |", "|---|---|---|",
          f"| CAGR | {_pct(s['cagr'])} | {_pct(s.get('bench_cagr'))} |",
          f"| Sharpe (rf {res.config['rf_annual']:.0%}) | {_num(s['sharpe'])} | {_num(s.get('bench_sharpe'))} |",
          f"| Max drawdown (MTM) | {_pct(s['max_drawdown'])} | {_pct(s.get('bench_max_drawdown'))} |",
          f"| Volatility | {_pct(s['vol'])} | |", f"| Sortino | {_num(s['sortino'])} | |",
          f"| Information ratio | {_num(s.get('information_ratio'))} | tracking error {_pct(s.get('tracking_error'))} |",
          f"| Beta | {_num(s.get('beta'))} | |", f"| Monthly hit rate | {_pct(s['hit_rate_monthly'])} | |",
          f"| Turnover (one-way, annual) | {_pct(s['turnover_annual'], 0)} | |",
          f"| Costs | {_num(s['costs_bps_annual'], 0)} bps/yr (₹{s['costs_total']:,.0f}) | |",
          f"| Median order / ADV20 | {_pct(s.get('median_participation'), 2)} | p90 {_pct(s.get('p90_participation'), 2)} |",
          f"| Rebalances / trades | {s['rebalances']} / {s['trades']} | |", ""]
    (out / "report.md").write_text("\n".join(md))
    (out / "report.json").write_text(json.dumps({"stats": s, "config": res.config}, indent=1, default=str))
    con.execute("INSERT OR REPLACE INTO backtests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [run_id, res.config["sleeve"]["name"], res.config["start"], res.config["end"],
                 json.dumps(res.config, default=str), json.dumps(s, default=str), None, "BACKTEST",
                 datetime.now(), str(out)])
    return out


def write_walkforward_report(con: duckdb.DuckDBPyConnection, wf: dict, run_id: str) -> Path:
    out = settings().reports_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    results = wf.pop("_results")
    oos, oos_b = wf.pop("_oos"), wf.pop("_oos_bench")
    if len(oos):
        pd.DataFrame({"strategy": (1 + oos).cumprod(), "bench": (1 + oos_b).cumprod()}).to_csv(out / "oos_equity.csv")
    for k, r in results.items():
        r.equity.rename("equity").to_frame().join(r.bench_equity.rename("bench")).to_csv(out / f"equity_{k}.csv")
    (out / "walkforward.json").write_text(json.dumps(wf, indent=1, default=str))
    acc, o, d, h = wf["acceptance"], wf["oos"], wf["dsr"], wf["holdout"]
    md = [f"# Walk-forward validation — Sleeve {wf['sleeve']}", "",
          f"Run `{run_id}` · {wf['start']} → {wf['end']} · holdout from {wf['holdout_start']} · capital ₹{wf['capital']:,.0f} · "
          f"{len(wf['grid'])} pre-registered trials", "",
          f"## Verdict: **{acc['verdict']}**", "", "| Check | Status | Detail |", "|---|---|---|"]
    md += [f"| {c['check']} | {c['status']} | {c['detail']} |" for c in acc["checks"]]
    md += ["", "## Out-of-sample (stitched folds, net of costs)", "",
           "| Metric | Strategy | Index |", "|---|---|---|",
           f"| CAGR | {_pct(o.get('cagr'))} | {_pct(o.get('bench_cagr'))} |",
           f"| Sharpe | {_num(o.get('sharpe'))} | {_num(o.get('bench_sharpe'))} |",
           f"| Max drawdown | {_pct(o.get('max_drawdown'))} | {_pct(o.get('bench_max_drawdown'))} |",
           f"| Information ratio | {_num(o.get('information_ratio'))} | |",
           f"| Deflated Sharpe p-value | {_num(d.get('p_value'), 3)} (SR0 {_num(d.get('sr0_annual'))}, trials {d.get('n_trials')}) | |",
           "", "## Folds", "", "| Year | Selected | Train Sharpe | Test Sharpe | Test CAGR | Index CAGR | Excess | Test maxDD |", "|---|---|---|---|---|---|---|---|"]
    md += [f"| {f['year']} | {f['selected']} | {f['train_sharpe']} | {f['test_sharpe']} | {_pct(f['test_cagr'])} | "
           f"{_pct(f['test_bench_cagr'])} | {_pct(f['test_excess_cagr'])} | {_pct(f['test_max_drawdown'])} |" for f in wf["folds"]]
    md += ["", f"## Holdout ({wf['holdout_start']} → {wf['end']}, evaluated once)", "",
           f"Selected `{h.get('selected')}` · CAGR {_pct(h.get('cagr'))} vs index {_pct(h.get('bench_cagr'))} · "
           f"Sharpe {_num(h.get('sharpe'))} · maxDD {_pct(h.get('max_drawdown'))} vs index {_pct(h.get('bench_max_drawdown'))}",
           "", "## Robustness (selected variant across N and liquidity floors)", "",
           "| Variant | Sharpe | CAGR | Excess | MaxDD |", "|---|---|---|---|---|"]
    md += [f"| {r['variant']} | {r['sharpe']} | {_pct(r['cagr'])} | {_pct(r['excess_cagr'])} | {_pct(r['max_drawdown'])} |" for r in wf["robustness"]]
    md += ["", "## All trials (full period, net)", "", "| Trial | CAGR | Sharpe | MaxDD | IR | Turnover | Costs bps |", "|---|---|---|---|---|---|---|"]
    md += [f"| {k} | {_pct(v.get('cagr'))} | {_num(v.get('sharpe'))} | {_pct(v.get('max_drawdown'))} | {_num(v.get('information_ratio'))} | "
           f"{_pct(v.get('turnover_annual'), 0)} | {_num(v.get('costs_bps_annual'), 0)} |" for k, v in wf["per_config"].items()]
    cap = wf["capacity"]
    md += ["", f"Capacity: median order {_pct(cap.get('median_participation'), 2)} of ADV20, p90 {_pct(cap.get('p90_participation'), 2)}; "
           f"turnover {_pct(cap.get('turnover_annual'), 0)}/yr; costs {_num(cap.get('costs_bps_annual'), 0)} bps/yr.", ""]
    (out / "report.md").write_text("\n".join(md))
    con.execute("INSERT OR REPLACE INTO backtests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [run_id, wf["sleeve"], wf["start"], wf["end"], json.dumps({"grid": wf["grid"], "capital": wf["capital"], "costs": wf["costs"]}),
                 json.dumps(o, default=str), json.dumps(acc, default=str), acc["verdict"], datetime.now(), str(out)])
    return out
