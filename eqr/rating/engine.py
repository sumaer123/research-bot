"""The rating engine: pure per-symbol evaluation over cross-sectional component scores.

`rate_symbol` has no I/O. `rate_universe` loads the PIT metric slice, scores the cross-section,
rates every name and (optionally) stores the `ratings` slice. Any weight / map / threshold /
gate change bumps ENGINE_VERSION and requires a fresh calibration (§6)."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import date
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from ..fundamentals.build import METRICS_VERSION, build_metrics, load_metrics
from ..fundamentals.base import load_inputs
from ..store import upsert
from .confidence import data_confidence, name_flags_for
from .decision import decide_full
from .flags import evaluate_flags
from .model import (OK, UNKNOWN, NA, Confidence, Decision, PillarScore, RatingResult, Valuation)
from .pillars import COMPONENTS, component_scores, composite, pillar_scores_for
from .sector import FINANCIAL, PILLARS, profile_weights

log = logging.getLogger("eqr.rating")

ENGINE_VERSION = "r1"
DEFAULT_VARIANT = "base"
THRESHOLDS = {"min_component_coverage": 0.60, "min_history_sessions": 120, "max_stmt_age_days": 400,
              "min_dci": 0.35, "pillar_known_share": 0.50}
VALUATION_MODELS = ("model_dcf_base", "model_dcf_bull", "model_dcf_bear", "model_ev_ebitda", "model_p_fcf",
                    "model_epv", "model_justified_pb", "model_ddm")

_CATALOGUE_SHA = hashlib.sha256(json.dumps(
    [{"name": c.name, "pillar": c.pillar, "kind": c.kind, "sign": c.sign, "weight": c.weight,
      "map": list(c.map_points), "profiles": sorted(c.profiles), "engine_min": c.engine_min, "llm": c.llm}
     for c in COMPONENTS], sort_keys=True).encode()).hexdigest()


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else f


def valuation_block(metrics: dict, price: Optional[float]) -> Valuation:
    models = {m: _f(metrics.get(m)) for m in VALUATION_MODELS}
    return Valuation(price=_f(price), fv_base=_f(metrics.get("fv_base")), fv_bull=_f(metrics.get("fv_bull")),
                     fv_bear=_f(metrics.get("fv_bear")), mos_base=_f(metrics.get("mos_base")),
                     implied_growth=_f(metrics.get("implied_growth")),
                     fundamental_growth=_f(metrics.get("fundamental_growth")), wacc=_f(metrics.get("wacc")),
                     models=models, dispersion=_f(metrics.get("val_dispersion")),
                     er_lo=_f(metrics.get("er_lo")), er_mid=_f(metrics.get("er_mid")), er_hi=_f(metrics.get("er_hi")))


def data_errors(metrics: dict, pillars: dict[str, PillarScore], component_coverage: float, feat: dict,
                notes: list[str]) -> list[str]:
    errs = []
    if component_coverage < THRESHOLDS["min_component_coverage"]:
        errs.append(f"component_coverage {component_coverage:.2f} < {THRESHOLDS['min_component_coverage']}")
    for p in ("P1_MOAT", "P6_VALUATION"):
        if pillars.get(p) is None or pillars[p].status != OK:
            errs.append(f"{p} UNKNOWN")
    hist = _f(feat.get("history_days"))
    if hist is not None and hist < THRESHOLDS["min_history_sessions"]:
        errs.append(f"history {hist:.0f} < {THRESHOLDS['min_history_sessions']} sessions")
    age = _f(feat.get("stmt_age_days"))
    if not feat:
        errs.append("not in the features universe on as_of")
    elif age is None:
        errs.append("no statements visible")
    elif age > THRESHOLDS["max_stmt_age_days"]:
        errs.append(f"statements {age:.0f} d old > {THRESHOLDS['max_stmt_age_days']}")
    if "deposits_outside_financial_industry" in notes and "profile_unmapped" in notes:
        errs.append("sector profile ambiguous")
    return errs


def rate_symbol(symbol: str, as_of: date, metrics: dict, status: dict, pillars: dict[str, PillarScore],
                profile: str, feat: dict, price: Optional[float], notes: list[str],
                prev_verdict: Optional[str] = None, variant: str = DEFAULT_VARIANT,
                engine: str = ENGINE_VERSION, source: str = "screener") -> RatingResult:
    """Pure: metrics (name -> value|None), status (name -> OK/UNKNOWN/NA), pre-computed pillar scores."""
    weights = profile_weights(profile, variant)
    S = composite(pillars, weights)
    w_known = sum(p.weight_known for p in pillars.values())
    w_total = sum(p.weight_total for p in pillars.values())
    cov = w_known / w_total if w_total else 0.0
    val = valuation_block(metrics, price)
    is_fin = profile in FINANCIAL
    flags = evaluate_flags(metrics, status, feat, profile, is_fin)
    nflags = name_flags_for(metrics, feat, notes)
    n_models = sum(1 for v in val.models.values() if v is not None)
    conf = data_confidence(pillars, cov, _f(feat.get("stmt_age_days")), source, val.dispersion, n_models, nflags)
    errs = data_errors(metrics, pillars, cov, feat, notes)
    if conf.dci < THRESHOLDS["min_dci"]:
        errs.append(f"DCI {conf.dci:.2f} < {THRESHOLDS['min_dci']}")
    timing = {k: _f(feat.get(k)) for k in ("mom_12_1", "mom_6_1", "dist_52w_high", "dma200_ratio")}
    p2 = pillars["P2_BALANCE"].score if "P2_BALANCE" in pillars else None
    p4 = pillars["P4_GROWTH"].score if "P4_GROWTH" in pillars else None
    if errs or S is None:
        dec = Decision(verdict="NO_RATING", rule_id="R0_DATA_ERROR", reason="; ".join(errs) or "no score",
                       conviction="LOW")
        status_out = "NO_RATING"
    else:
        dec = decide_full(S, val.mos_base, conf, flags, metrics, p2, p4, prev_verdict)
        status_out = "RATED"
    manifest = {
        "engine_version": engine, "variant": variant, "profile": profile, "symbol": symbol, "as_of": str(as_of),
        "metrics_version": METRICS_VERSION, "catalogue_sha": _CATALOGUE_SHA, "weights": weights,
        "thresholds": THRESHOLDS, "source": source,
        "inputs": [{"metric": k, "value": _f(v), "status": status.get(k, UNKNOWN)} for k, v in sorted(metrics.items())],
        "pillars": {k: {"score": p.score, "status": p.status, "known": p.weight_known, "total": p.weight_total}
                    for k, p in pillars.items()},
        "flags": [f.code for f in flags], "name_flags": nflags,
        "valuation": {"fv_base": val.fv_base, "fv_bull": val.fv_bull, "fv_bear": val.fv_bear,
                      "mos_base": val.mos_base, "models": val.models, "price": val.price},
        "prev_verdict": prev_verdict,
    }
    sha = hashlib.sha256(json.dumps(manifest, sort_keys=True, default=str).encode()).hexdigest()
    return RatingResult(symbol=symbol, as_of=as_of, engine_version=engine, variant=variant, profile=profile,
                        score=None if S is None else float(S), pillars=pillars, red_flags=flags, valuation=val,
                        confidence=conf, decision=dec, status=status_out, data_errors=errs, manifest=manifest,
                        manifest_sha=sha, timing=timing)


def previous_verdicts(con: duckdb.DuckDBPyConnection, as_of: date, engine: str, variant: str) -> dict[str, str]:
    rows = con.execute("""SELECT symbol, rating FROM ratings WHERE engine_version = ? AND variant = ? AND status = 'RATED'
                          AND as_of = (SELECT max(as_of) FROM ratings WHERE engine_version = ? AND variant = ? AND as_of < ?)""",
                       [engine, variant, engine, variant, as_of]).fetchall()
    return {r[0]: r[1] for r in rows}


def rate_universe(con: duckdb.DuckDBPyConnection, as_of: date, variant: str = DEFAULT_VARIANT,
                  engine: str = ENGINE_VERSION, symbols: Optional[list[str]] = None, store: bool = True,
                  recompute_metrics: bool = False, prev: Optional[dict[str, str]] = None,
                  use_hysteresis: bool = True, store_metrics: Optional[bool] = None,
                  inputs: Optional[dict] = None, wide: Optional[pd.DataFrame] = None) -> list[RatingResult]:
    """Rate every name in the features universe on as_of (or `symbols`). `inputs`/`wide` may be
    passed by a caller that scores several variants on the same date."""
    if inputs is None:
        inputs = load_inputs(con, as_of, symbols, with_xbrl=engine != "r1")
    if not inputs:
        return []
    syms = list(inputs)
    if wide is None:
        wide = pd.DataFrame()
        if not recompute_metrics:
            wide = load_metrics(con, as_of, syms)
        if wide.empty or len(wide) < len(syms) * 0.9:
            wide = build_metrics(con, as_of, syms, store=store if store_metrics is None else store_metrics,
                                 with_xbrl=engine != "r1")
    if wide.empty:
        return []
    status_df: pd.DataFrame = wide.attrs.get("status", pd.DataFrame())
    wide = wide.copy(deep=False); wide.attrs = {}                      # attrs are deep-copied on every access
    profile = pd.Series({s: inputs[s].profile for s in wide.index})
    scores, priors = component_scores(wide, groups=profile, profile_of=profile, engine=engine, variant=variant)
    score_rows = scores.to_dict("index")
    raw_rows = wide.to_dict("index")
    status_rows = status_df.to_dict("index") if not status_df.empty else {}
    prev = prev if prev is not None else (previous_verdicts(con, as_of, engine, variant) if use_hysteresis else {})
    source = "xbrl" if any(inputs[s].xbrl for s in syms[:50]) else "screener"
    results: list[RatingResult] = []
    for sym in wide.index:
        inp = inputs[sym]
        metrics = {k: _f(v) for k, v in raw_rows[sym].items()}
        srow = status_rows.get(sym, {})
        st = {k: (srow[k] if isinstance(srow.get(k), str) else (OK if metrics.get(k) is not None else UNKNOWN))
              for k in metrics}
        pillars = pillar_scores_for(sym, scores, wide, inp.profile, engine, variant, priors=priors,
                                    min_known_share=THRESHOLDS["pillar_known_share"],
                                    score_row=score_rows[sym], raw_row=raw_rows[sym])
        try:
            r = rate_symbol(sym, as_of, metrics, st, pillars, inp.profile, inp.feat, inp.price, inp.notes,
                            prev_verdict=prev.get(sym), variant=variant, engine=engine, source=source)
        except Exception as e:                     # noqa: BLE001 - one name never blocks the slice
            log.warning("rating failed for %s on %s: %s", sym, as_of, e)
            continue
        results.append(r)
    if store and results:
        con.execute("DELETE FROM ratings WHERE as_of = ? AND engine_version = ? AND variant = ?"
                    + (" AND symbol IN (" + ",".join("?" * len(syms)) + ")" if symbols else ""),
                    [as_of, engine, variant, *(syms if symbols else [])])
        upsert(con, "ratings", pd.DataFrame([r.to_row() for r in results]))
    return results


def summary(results: list[RatingResult]) -> dict:
    out = {"n": len(results), "rated": sum(r.status == "RATED" for r in results), "verdicts": {}, "bands": {},
           "profiles": {}}
    for r in results:
        out["verdicts"][r.decision.verdict] = out["verdicts"].get(r.decision.verdict, 0) + 1
        out["bands"][r.confidence.band] = out["bands"].get(r.confidence.band, 0) + 1
        out["profiles"][r.profile] = out["profiles"].get(r.profile, 0) + 1
    return out
