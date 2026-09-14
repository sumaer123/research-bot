"""Sector-specific KPIs for BANK and NBFC profiles from XBRL.

Informational metrics prefixed with 'kpi_'.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from .base import Inputs, MetricSet, ok


def compute(inp: Inputs, ctx: dict | None = None) -> MetricSet:
    """Compute sector-specific XBRL KPIs for BANK and NBFC profiles.

    Returns:
        MetricSet with informational metrics (kpi_*) when XBRL data is present, else empty.
    """
    result = MetricSet()

    if not inp.xbrl:
        return result

    # BANK KPIs
    if inp.is_bank:
        kpi_cet1 = inp.xbrl.get("cet1")
        if kpi_cet1 is not None and math.isfinite(kpi_cet1):
            result.add(ok("kpi_cet1", kpi_cet1 / 100.0, unit="ratio"))

        kpi_car = inp.xbrl.get("capital_adequacy_ratio")
        if kpi_car is not None and math.isfinite(kpi_car):
            result.add(ok("kpi_car", kpi_car / 100.0, unit="ratio"))

        kpi_gnpa = inp.xbrl.get("gross_npa")
        if kpi_gnpa is not None and math.isfinite(kpi_gnpa):
            result.add(ok("kpi_gnpa", kpi_gnpa, unit="crore"))

        kpi_nnpa = inp.xbrl.get("net_npa")
        if kpi_nnpa is not None and math.isfinite(kpi_nnpa):
            result.add(ok("kpi_nnpa", kpi_nnpa, unit="crore"))

        kpi_roa = inp.xbrl.get("return_on_assets")
        if kpi_roa is not None and math.isfinite(kpi_roa):
            result.add(ok("kpi_roa", kpi_roa / 100.0, unit="ratio"))

        kpi_advances = inp.xbrl.get("advances")
        if kpi_advances is not None and math.isfinite(kpi_advances):
            result.add(ok("kpi_advances", kpi_advances, unit="crore"))

        kpi_deposits = inp.xbrl.get("deposits")
        if kpi_deposits is not None and math.isfinite(kpi_deposits):
            result.add(ok("kpi_deposits", kpi_deposits, unit="crore"))

        kpi_provisions = inp.xbrl.get("provisions")
        if kpi_provisions is not None and math.isfinite(kpi_provisions):
            result.add(ok("kpi_provisions", kpi_provisions, unit="crore"))

    # NBFC_FIN KPIs
    elif inp.is_financial:  # NBFC_FIN
        kpi_gnpa = inp.xbrl.get("gross_npa")
        if kpi_gnpa is not None and math.isfinite(kpi_gnpa):
            result.add(ok("kpi_gnpa", kpi_gnpa, unit="crore"))

        kpi_nnpa = inp.xbrl.get("net_npa")
        if kpi_nnpa is not None and math.isfinite(kpi_nnpa):
            result.add(ok("kpi_nnpa", kpi_nnpa, unit="crore"))

        kpi_roa = inp.xbrl.get("return_on_assets")
        if kpi_roa is not None and math.isfinite(kpi_roa):
            result.add(ok("kpi_roa", kpi_roa / 100.0, unit="ratio"))

    return result
