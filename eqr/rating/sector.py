"""Sector profiles: which component set and pillar weights apply to a name.

The map is data over the ACTUAL NSE industry vocabulary in `instruments.industry`
(73 strings observed 2026-09-14). `tests/test_rating_sector.py` asserts every string in
`tests/fixtures/nse_industries.txt` is explicitly mapped; an unmapped string falls to
GENERAL with the note `profile_unmapped` (a name-level DCI flag), never silently."""
from __future__ import annotations

from typing import Optional

GENERAL, BANK, NBFC_FIN, IT_SERVICES, PHARMA, CYCLICAL = (
    "GENERAL", "BANK", "NBFC_FIN", "IT_SERVICES", "PHARMA", "CYCLICAL")
PROFILES = (GENERAL, BANK, NBFC_FIN, IT_SERVICES, PHARMA, CYCLICAL)
FINANCIAL = frozenset({BANK, NBFC_FIN})

_BANK = {"Banks"}
_NBFC = {"Finance", "Financial Services", "Financial Technology (Fintech)", "Capital Markets", "Insurance"}
_IT = {"IT - Software", "IT - Services", "Information Technology"}
_PHARMA = {"Pharmaceuticals & Biotechnology", "Healthcare", "Healthcare Services", "Healthcare Equipment & Supplies"}
_CYCLICAL = {"Metals & Mining", "Ferrous Metals", "Non - Ferrous Metals", "Diversified Metals", "Minerals & Mining",
             "Metals & Minerals Trading", "Cement & Cement Products", "Construction Materials",
             "Other Construction Materials", "Oil", "Oil Gas & Consumable Fuels", "Petroleum Products",
             "Consumable Fuels", "Chemicals & Petrochemicals", "Fertilizers & Agrochemicals",
             "Paper, Forest & Jute Products", "Textiles", "Textiles & Apparels", "Realty"}
_GENERAL = {"Aerospace & Defense", "Agricultural Food & other Products",
            "Agricultural, Commercial & Construction Vehicles", "Auto Components",
            "Automobile and Auto Components", "Automobiles", "Beverages", "Capital Goods", "Chemicals",
            "Cigarettes & Tobacco Products", "Commercial Services & Supplies", "Construction",
            "Consumer Durables", "Consumer Services", "Diversified", "Diversified FMCG",
            "Electrical Equipment", "Engineering Services", "Entertainment", "Fast Moving Consumer Goods",
            "Food Products", "Gas", "Household Products", "IT - Hardware", "Industrial Manufacturing",
            "Industrial Products", "Leisure Services", "Media", "Media Entertainment & Publication",
            "Other Consumer Services", "Other Utilities", "Personal Products", "Power",
            "Printing & Publication", "Retailing", "Services", "Telecom - Equipment & Accessories",
            "Telecom - Services", "Telecommunication", "Transport Infrastructure", "Transport Services"}
_REGULATED = {"Power", "Gas", "Other Utilities", "Telecom - Services", "Transport Infrastructure"}

SECTOR_PROFILE_MAP: dict[str, str] = {}
for _s, _p in ((_BANK, BANK), (_NBFC, NBFC_FIN), (_IT, IT_SERVICES), (_PHARMA, PHARMA),
               (_CYCLICAL, CYCLICAL), (_GENERAL, GENERAL)):
    for _name in _s:
        SECTOR_PROFILE_MAP[_name] = _p


def profile_for(industry: Optional[str], has_deposits: bool = False, xbrl_bank: bool = False) -> tuple[str, list[str]]:
    """(profile, notes). Deposits on the balance sheet or XBRL bank markers force BANK even
    when the industry string says otherwise (co-operative / small-finance banks land in
    `Finance` on NSE)."""
    notes: list[str] = []
    if has_deposits or xbrl_bank:
        if industry in _BANK or industry in _NBFC or industry is None:
            return BANK, notes
        notes.append("deposits_outside_financial_industry")
    if industry is None:
        return GENERAL, ["profile_unmapped"]
    p = SECTOR_PROFILE_MAP.get(industry)
    if p is None:
        return GENERAL, ["profile_unmapped"]
    if industry == "Insurance":
        notes.append("insurance_metrics_partial")
    if industry in _REGULATED:
        notes.append("regulated")
    return p, notes


# pillar weights per profile (base variant); every column sums to 1.0 (tested)
PILLARS = ("P1_MOAT", "P2_BALANCE", "P3_EARNINGS", "P4_GROWTH", "P5_MANAGEMENT", "P6_VALUATION")
BASE_WEIGHTS: dict[str, dict[str, float]] = {
    GENERAL:     {"P1_MOAT": 0.20, "P2_BALANCE": 0.15, "P3_EARNINGS": 0.15, "P4_GROWTH": 0.15, "P5_MANAGEMENT": 0.10, "P6_VALUATION": 0.25},
    BANK:        {"P1_MOAT": 0.25, "P2_BALANCE": 0.25, "P3_EARNINGS": 0.15, "P4_GROWTH": 0.10, "P5_MANAGEMENT": 0.10, "P6_VALUATION": 0.15},
    NBFC_FIN:    {"P1_MOAT": 0.20, "P2_BALANCE": 0.30, "P3_EARNINGS": 0.15, "P4_GROWTH": 0.10, "P5_MANAGEMENT": 0.10, "P6_VALUATION": 0.15},
    IT_SERVICES: {"P1_MOAT": 0.25, "P2_BALANCE": 0.05, "P3_EARNINGS": 0.15, "P4_GROWTH": 0.20, "P5_MANAGEMENT": 0.15, "P6_VALUATION": 0.20},
    PHARMA:      {"P1_MOAT": 0.20, "P2_BALANCE": 0.10, "P3_EARNINGS": 0.20, "P4_GROWTH": 0.15, "P5_MANAGEMENT": 0.15, "P6_VALUATION": 0.20},
    CYCLICAL:    {"P1_MOAT": 0.15, "P2_BALANCE": 0.25, "P3_EARNINGS": 0.15, "P4_GROWTH": 0.10, "P5_MANAGEMENT": 0.10, "P6_VALUATION": 0.25},
}
VARIANT_DELTAS: dict[str, dict[str, float]] = {
    "base": {},
    "quality_tilt": {"P1_MOAT": +0.05, "P3_EARNINGS": +0.05, "P6_VALUATION": -0.10},
    "value_tilt": {"P6_VALUATION": +0.10, "P1_MOAT": -0.05, "P4_GROWTH": -0.05},
    "with_qual": {},          # r3: same weights, LLM grades allowed inside pillars (never the published default)
}
VARIANTS = tuple(VARIANT_DELTAS)


def profile_weights(profile: str, variant: str = "base") -> dict[str, float]:
    if profile not in BASE_WEIGHTS:
        raise KeyError(f"unknown profile {profile}")
    if variant not in VARIANT_DELTAS:
        raise KeyError(f"unknown variant {variant}")
    w = dict(BASE_WEIGHTS[profile])
    for k, d in VARIANT_DELTAS[variant].items():
        w[k] = round(w[k] + d, 4)
    if any(v < 0 for v in w.values()):
        raise ValueError(f"negative weight for {profile}/{variant}: {w}")
    return w
