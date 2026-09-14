"""Dataclasses shared by the rating engine (pure data, no behaviour beyond serialisation)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Literal, Optional

OK, UNKNOWN, NA = "OK", "UNKNOWN", "NA"

Kind = Literal["pct", "map", "binary", "level"]
Tier = Literal["HARD", "SOFT", "WATCH"]
Verdict = Literal["CONVICTION_BUY", "SPECULATIVE_BUY", "HOLD", "TRIM", "SELL", "NO_RATING"]
VERDICT_ORDER: dict[str, int] = {"SELL": 0, "TRIM": 1, "HOLD": 2, "SPECULATIVE_BUY": 3, "CONVICTION_BUY": 4}


@dataclass(frozen=True)
class Component:
    name: str                       # metric name in fund_metrics
    pillar: str                     # P1_MOAT .. P6_VALUATION
    kind: str                       # pct | map | binary
    sign: int = +1                  # pct only: +1 higher is better, -1 lower is better
    weight: float = 1.0
    map_points: tuple[tuple[float, float], ...] = ()     # (x, score) piecewise-linear, x ascending
    profiles: frozenset = frozenset({"ALL"})            # profiles that use it ("ALL" = every profile)
    engine_min: str = "r1"          # r1 | r2 | r3
    llm: bool = False               # True only for verified dossier grades (with_qual variant)

    def applies(self, profile: str, engine: str, variant: str) -> bool:
        if "ALL" not in self.profiles and profile not in self.profiles:
            return False
        if _engine_rank(self.engine_min) > _engine_rank(engine):
            return False
        if self.llm and variant != "with_qual":
            return False
        return True


def _engine_rank(v: str) -> int:
    return {"r1": 1, "r2": 2, "r3": 3}.get(v, 1)


@dataclass
class ComponentScore:
    name: str
    raw: Optional[float]
    score: Optional[float]          # 0..100 when known, else the prior actually used
    status: str                     # OK | UNKNOWN | NA
    weight: float
    provenance: str = ""
    shrunk_to_prior: bool = False
    prior: Optional[float] = None


@dataclass
class PillarScore:
    name: str
    score: Optional[float]
    status: str
    weight_known: float
    weight_total: float
    components: list[ComponentScore] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.weight_known / self.weight_total if self.weight_total > 0 else 0.0


@dataclass
class RedFlag:
    code: str
    tier: str                       # HARD | SOFT | WATCH
    cap: Optional[str]              # max verdict allowed (HARD -> SELL, SOFT -> HOLD/TRIM, WATCH -> None)
    evidence: str
    source: str
    value: Optional[float] = None


@dataclass
class Valuation:
    price: Optional[float]
    fv_base: Optional[float]
    fv_bull: Optional[float]
    fv_bear: Optional[float]
    mos_base: Optional[float]
    implied_growth: Optional[float]
    fundamental_growth: Optional[float]
    wacc: Optional[float]
    models: dict = field(default_factory=dict)           # model -> fair value per share (None when NA)
    dispersion: Optional[float] = None                   # (max - min) / median across available models
    er_lo: Optional[float] = None
    er_mid: Optional[float] = None
    er_hi: Optional[float] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Confidence:
    dci: float
    band: str                       # HIGH | MED | LOW | NONE
    component_coverage: float
    pillar_coverage: float
    staleness_factor: float
    source_factor: float
    dispersion_factor: float
    name_flag_factor: float
    flags: list[str] = field(default_factory=list)


@dataclass
class Decision:
    verdict: str
    rule_id: str
    reason: str
    conviction: str                 # HIGH | MED | LOW
    downgraded_by_confidence: bool = False
    capped_by: Optional[str] = None
    verdict_before_caps: Optional[str] = None
    hysteresis_applied: bool = False


@dataclass
class RatingResult:
    symbol: str
    as_of: date
    engine_version: str
    variant: str
    profile: str
    score: Optional[float]
    pillars: dict[str, PillarScore]
    red_flags: list[RedFlag]
    valuation: Valuation
    confidence: Confidence
    decision: Decision
    status: str                     # RATED | NO_RATING
    data_errors: list[str]
    manifest: dict
    manifest_sha: str
    timing: dict = field(default_factory=dict)     # momentum tags, informational

    def to_row(self) -> dict:
        v, c, d = self.valuation, self.confidence, self.decision
        return {
            "symbol": self.symbol, "as_of": self.as_of, "engine_version": self.engine_version,
            "variant": self.variant, "status": self.status, "rating": d.verdict, "score": self.score,
            "confidence": c.dci, "confidence_band": c.band, "er_lo": v.er_lo, "er_mid": v.er_mid, "er_hi": v.er_hi,
            "coverage": c.component_coverage,
            "pillars_json": json.dumps({k: _pillar_dict(p) for k, p in self.pillars.items()}, default=_json_default),
            "gates_json": json.dumps([asdict(f) for f in self.red_flags], default=_json_default),
            "manifest_json": json.dumps(self.manifest, default=_json_default, sort_keys=True),
            "manifest_sha": self.manifest_sha,
            "data_errors_json": json.dumps(self.data_errors),
            "created_at": datetime.now(),
            "rule_id": d.rule_id, "profile": self.profile, "mos_base": v.mos_base,
            "fv_base": v.fv_base, "fv_bull": v.fv_bull, "fv_bear": v.fv_bear, "dci_band": c.band,
            "valuation_json": json.dumps(asdict(v), default=_json_default),
            "decision_json": json.dumps({**asdict(d), "confidence": asdict(c), "timing": self.timing}, default=_json_default),
            "price": v.price,
        }


def _pillar_dict(p: PillarScore) -> dict:
    return {"score": p.score, "status": p.status, "coverage": p.coverage, "weight_known": p.weight_known,
            "weight_total": p.weight_total,
            "components": [asdict(c) for c in p.components]}


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if hasattr(o, "item"):
        return o.item()
    return str(o)
