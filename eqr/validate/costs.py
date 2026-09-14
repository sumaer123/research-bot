"""Indian delivery-equity transaction costs, per order, on a stated order value.
Statutory rates as of 2026 (STT 0.1% each side on delivery; stamp 0.015% buy;
NSE transaction charge 0.00297%; SEBI Rs 10/crore; GST 18% on broker+exchange+SEBI);
DP charge per sell scrip-day; square-root impact model (10 bps + 50 bps x sqrt(participation)) capped at 100 bps."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import sqrt
from typing import Optional


@dataclass(frozen=True)
class CostModel:
    brokerage_per_order: float = 20.0
    brokerage_pct: float = 0.0
    stt_pct: float = 0.1
    exchange_pct: float = 0.00297
    sebi_per_cr: float = 10.0
    stamp_buy_pct: float = 0.015
    gst_pct: float = 18.0
    dp_charge_per_sell: float = 15.34
    impact_base_bps: float = 10.0
    impact_k_bps: float = 50.0
    impact_cap_bps: float = 100.0

    def order_cost(self, side: str, value: float, adv20: Optional[float]) -> dict:
        side = side.upper()
        if value <= 0:
            return {"total": 0.0, "explicit": 0.0, "impact": 0.0, "bps": 0.0, "participation": 0.0}
        brokerage = self.brokerage_per_order + value * self.brokerage_pct / 100
        stt = value * self.stt_pct / 100
        exch = value * self.exchange_pct / 100
        sebi = value / 1e7 * self.sebi_per_cr
        stamp = value * self.stamp_buy_pct / 100 if side == "BUY" else 0.0
        gst = (brokerage + exch + sebi) * self.gst_pct / 100
        dp = self.dp_charge_per_sell if side == "SELL" else 0.0
        explicit = brokerage + stt + exch + sebi + stamp + gst + dp
        part = value / adv20 if adv20 and adv20 > 0 else 0.05
        impact_bps = min(self.impact_cap_bps, self.impact_base_bps + self.impact_k_bps * sqrt(part))
        impact = value * impact_bps / 1e4
        total = explicit + impact
        return {"total": round(total, 2), "explicit": round(explicit, 2), "impact": round(impact, 2),
                "bps": round(total / value * 1e4, 2), "participation": round(part, 4),
                "brokerage": round(brokerage, 2), "stt": round(stt, 2), "stamp": round(stamp, 2),
                "gst": round(gst, 2), "dp": dp}

    def to_dict(self) -> dict:
        return asdict(self)


DISCOUNT_BROKER = CostModel(brokerage_per_order=20.0)
ZERO_BROKERAGE = CostModel(brokerage_per_order=0.0)
