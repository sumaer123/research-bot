"""The pre-registered acceptance bar (spec section 7). Written before any result was seen."""
from __future__ import annotations

BAR = {
    "oos_sharpe_min": 0.8,
    "oos_ir_min": 0.5,
    "dsr_p_max": 0.05,
    "recent_folds_positive_min": 3,     # of the 4 most recent folds
    "robust_sharpe_min": 0.5,           # every robustness variant
    "capacity_median_participation_max": 0.05,
}


def evaluate(oos: dict, folds: list[dict], dsr: dict, robustness: list[dict], capacity: dict) -> dict:
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    sh = oos.get("sharpe", float("nan"))
    add("oos_sharpe", sh >= BAR["oos_sharpe_min"], f"OOS Sharpe {sh:.2f} vs >= {BAR['oos_sharpe_min']}")
    ir = oos.get("information_ratio", float("nan"))
    add("oos_information_ratio", ir >= BAR["oos_ir_min"], f"IR vs NIFTY 500 TR proxy {ir:.2f} vs >= {BAR['oos_ir_min']}")
    dd, bdd = oos.get("max_drawdown", float("nan")), oos.get("bench_max_drawdown", float("nan"))
    add("oos_drawdown_not_worse_than_index", dd >= bdd, f"strategy MTM maxDD {dd:.1%} vs index {bdd:.1%}")
    pv = dsr.get("p_value", float("nan"))
    add("deflated_sharpe", pv < BAR["dsr_p_max"], f"DSR p-value {pv:.3f} (trials {dsr.get('n_trials')}) vs < {BAR['dsr_p_max']}")
    recent = [f for f in folds if f.get("test_days", 0) > 0][-4:]
    pos = sum(1 for f in recent if f.get("test_excess_cagr", 0) > 0)
    add("recent_folds_positive_excess", pos >= BAR["recent_folds_positive_min"] and len(recent) >= 4,
        f"{pos} of {len(recent)} most recent folds beat the index")
    if robustness:
        worst = min(r.get("sharpe", float("nan")) for r in robustness)
        all_pos = all(r.get("excess_cagr", 0) > 0 for r in robustness)
        add("robust_across_variants", worst >= BAR["robust_sharpe_min"] and all_pos,
            f"worst variant Sharpe {worst:.2f}, all variants beat index: {all_pos} ({len(robustness)} variants)")
    else:
        add("robust_across_variants", False, "no robustness variants run")
    mp = capacity.get("median_participation", float("nan"))
    add("capacity", mp < BAR["capacity_median_participation_max"], f"median order {mp:.2%} of ADV20 at the stated capital")
    verdict = "VALIDATED" if all(c["status"] == "PASS" for c in checks) else "NOT VALIDATED"
    return {"verdict": verdict, "checks": checks, "bar": BAR}
