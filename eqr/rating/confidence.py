"""Data Confidence Index (DCI) calculation (methodology plan §3.4).

DCI = (0.45·component_coverage + 0.15·pillar_coverage + 0.40) × staleness × source × val_dispersion × name_flags

Band: HIGH ≥ 0.75 · MED ≥ 0.50 · LOW ≥ 0.35 · NONE < 0.35
"""
from __future__ import annotations

from .model import Confidence, PillarScore, OK


def data_confidence(
    pillars: dict[str, PillarScore],
    component_coverage: float,
    staleness_days: float | None,
    source: str,
    dispersion: float | None,
    n_models: int,
    name_flags: list[str]
) -> Confidence:
    """Calculate Data Confidence Index (DCI) per methodology plan §3.4.

    Args:
        pillars: dict of pillar_name -> PillarScore
        component_coverage: weighted share of known components (0..1)
        staleness_days: days since latest statement
        source: 'xbrl' or 'screener' (or 'screener_disagree' for screener with XBRL conflict)
        dispersion: (max - min) / median of fair-value model estimates (0..1)
        n_models: number of valuation models with valid output
        name_flags: list of name-level integrity items (len used in calculation)

    Returns:
        Confidence dataclass with DCI and band.
    """
    # pillar_coverage = share of pillars with status OK among 6
    pillar_coverage = sum(1 for p in pillars.values() if p.status == OK) / 6.0

    # staleness factor
    if staleness_days is None:
        staleness_factor = 0.70  # unknown staleness
    elif staleness_days <= 120:
        staleness_factor = 1.00
    elif staleness_days <= 200:
        staleness_factor = 0.85
    elif staleness_days <= 400:
        staleness_factor = 0.70
    else:
        staleness_factor = 0.70

    # source factor
    if source == "xbrl":
        source_factor = 1.00
    elif source == "screener":
        source_factor = 0.90
    elif source == "screener_disagree":  # screener with XBRL FY sales disagree > 10%
        source_factor = 0.90 * 0.85
    else:
        source_factor = 0.90

    # val_dispersion factor
    if dispersion is None or n_models < 2:
        val_disp_factor = 0.70
    elif dispersion <= 0.25:
        val_disp_factor = 1.00
    elif dispersion <= 0.50:
        val_disp_factor = 0.85
    else:
        val_disp_factor = 0.70

    # name_flags factor (only NAME-SPECIFIC items, not universe-wide)
    name_flag_factor = 0.90 ** len(name_flags)

    # DCI formula
    dci = (0.45 * component_coverage + 0.15 * pillar_coverage + 0.40) * staleness_factor * source_factor * val_disp_factor * name_flag_factor

    # Clamp to [0, 1]
    dci = max(0.0, min(1.0, dci))

    # Band
    if dci >= 0.75:
        band = "HIGH"
    elif dci >= 0.50:
        band = "MED"
    elif dci >= 0.35:
        band = "LOW"
    else:
        band = "NONE"

    return Confidence(
        dci=dci,
        band=band,
        component_coverage=component_coverage,
        pillar_coverage=pillar_coverage,
        staleness_factor=staleness_factor,
        source_factor=source_factor,
        dispersion_factor=val_disp_factor,
        name_flag_factor=name_flag_factor,
        flags=name_flags
    )


def name_flags_for(metrics: dict[str, float | None], feat: dict, notes: list[str]) -> list[str]:
    """Identify NAME-SPECIFIC integrity items that affect DCI.

    NAME-SPECIFIC items (penalised in DCI):
        - implausible P/E (> 200, or < 0 with PAT > 0)
        - PAT CAGR discontinuity > 150%
        - history < 240 sessions (feat history_days)
        - 'borrowing_conflict' in notes
        - 'profile_unmapped' in notes

    Universe-wide items (NOT in DCI, live on claim ladder):
        MCAP_NOT_SPLIT_INVARIANT, AS_RESTATED_FUNDAMENTALS, BENCH_PROXY, CONTROLS_NO_HISTORY

    Returns:
        List of flag codes (NAME-SPECIFIC only).
    """
    flags: list[str] = []

    # Implausible P/E
    pe_ttm = feat.get("pe_ttm")
    pat_ttm = metrics.get("pat_ttm")
    if pe_ttm is not None and (pe_ttm > 200 or (pe_ttm < 0 and pat_ttm is not None and pat_ttm > 0)):
        flags.append("NAME_IMPLAUSIBLE_PE")

    # PAT CAGR discontinuity > 150%
    pat_cagr = metrics.get("pat_cagr_5y")
    if pat_cagr is not None and abs(pat_cagr) > 1.5:
        flags.append("NAME_PAT_CAGR_DISCONTINUITY")

    # history < 240 sessions
    history_days = feat.get("history_days")
    if history_days is not None and history_days < 240:
        flags.append("NAME_HISTORY_LT_240")

    # borrowing_conflict in notes
    if "borrowing_conflict" in notes:
        flags.append("NAME_BORROWING_CONFLICT")

    # profile_unmapped in notes
    if "profile_unmapped" in notes:
        flags.append("NAME_PROFILE_UNMAPPED")

    return flags
