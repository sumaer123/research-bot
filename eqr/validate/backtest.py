"""Portfolio simulator: signal at the close of a rebalance session, fills at the next
session's open, daily MTM from adjusted closes, explicit + impact costs per order,
stop-loss exits (S), delisting exits with a haircut. No look-ahead by construction:
the only inputs at a signal date are features built from data visible on that date."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Callable, Optional

import duckdb
import numpy as np
import pandas as pd

from ..features.build import get_features
from ..features.panel import PricePanel, load_panel, window_start
from ..spine.universe import month_end_sessions, week_end_sessions
from ..store.pit import index_series
from ..strategy.regime import regime_table, regime_at
from ..strategy.sizing import inverse_vol_weights
from ..strategy.sleeves import SleeveConfig, score, select
from .costs import CostModel, DISCOUNT_BROKER
from .metrics import summarize

BENCH_YIELD = 0.013          # NIFTY 500 dividend yield assumed for the TR proxy


@dataclass
class BacktestConfig:
    sleeve: SleeveConfig
    start: date
    end: date
    capital: float = 1_000_000.0
    costs: CostModel = DISCOUNT_BROKER
    rebalance_band: float = 0.01
    delist_haircut: float = 0.01
    delist_after_sessions: int = 5
    rf_annual: float = 0.06
    reuse_features: bool = True
    base_min_turnover_inr: float = 1e7

    def to_dict(self) -> dict:
        d = asdict(self)
        d["costs"] = self.costs.to_dict()
        d["start"], d["end"] = str(self.start), str(self.end)
        return d


@dataclass
class BacktestResult:
    equity: pd.Series
    cash: pd.Series
    exposure: pd.Series
    trades: pd.DataFrame
    holdings: dict
    bench_equity: pd.Series
    stats: dict
    config: dict
    daily_returns: pd.Series = field(default=None)

    def __post_init__(self):
        self.daily_returns = self.equity.pct_change().dropna()


def _bench(con, start: date, end: date, index_name: str = "Nifty 500") -> pd.Series:
    b = index_series(con, index_name, start=start, end=end)
    s = pd.Series(b.close.values, index=pd.to_datetime(b.trade_date))
    r = s.pct_change().fillna(0) + BENCH_YIELD / 252
    return (1 + r).cumprod() * 100


def run_backtest(con: duckdb.DuckDBPyConnection, cfg: BacktestConfig, panel: Optional[PricePanel] = None,
                 reg: Optional[pd.DataFrame] = None, progress: Optional[Callable[[str], None]] = None,
                 feature_cache: Optional[dict] = None) -> BacktestResult:
    sl = cfg.sleeve
    panel = panel or load_panel(con, window_start(cfg.start, 420), cfg.end, series=("EQ", "BE", "BZ"))
    dates = panel.dates
    i0 = int(dates.searchsorted(pd.Timestamp(cfg.start), side="left"))
    i1 = int(dates.searchsorted(pd.Timestamp(cfg.end), side="right") - 1)
    if i1 <= i0 + 5:
        raise ValueError("backtest window too short")
    reb_dates = (month_end_sessions if sl.rebalance == "M" else week_end_sessions)(con, cfg.start, cfg.end)
    reb_pos = {int(dates.searchsorted(pd.Timestamp(d), side="left")) for d in reb_dates}
    reg = regime_table(con, end=cfg.end) if reg is None else reg
    feature_cache = {} if feature_cache is None else feature_cache

    cash = float(cfg.capital)
    pos: dict[str, dict] = {}
    pending_target: Optional[pd.Series] = None
    pending_adv: dict = {}
    pending_exits: set[str] = set()
    trades: list[dict] = []
    equity_hist, cash_hist, expo_hist, holdings = [], [], [], {}
    gross_traded = 0.0
    costs_total = 0.0
    n_reb = 0

    opens, closes = panel.open, panel.close
    close_arr = closes.to_numpy()
    open_arr = opens.to_numpy()
    col = {s: j for j, s in enumerate(closes.columns)}

    def px(arr, i, sym):
        j = col.get(sym)
        return float(arr[i, j]) if j is not None else float("nan")

    def sell(sym: str, i: int, price: float, reason: str):
        nonlocal cash, gross_traded, costs_total
        p = pos.pop(sym)
        value = p["shares"] * price
        oc = cfg.costs.order_cost("SELL", value, p.get("adv20"))
        c = oc["total"]
        cash += value - c
        gross_traded += value
        costs_total += c
        trades.append({"date": dates[i], "symbol": sym, "side": "SELL", "qty": p["shares"], "price": price,
                       "value": value, "cost": c, "participation": oc["participation"], "reason": reason,
                       "pnl": (price - p["entry_px"]) * p["shares"]})

    def buy(sym: str, i: int, price: float, value: float, adv20, reason: str):
        nonlocal cash, gross_traded, costs_total
        qty = int(value // price)
        if qty <= 0:
            return
        value = qty * price
        oc = cfg.costs.order_cost("BUY", value, adv20)
        c = oc["total"]
        if value + c > cash:
            qty = int((cash - c) // price)
            if qty <= 0:
                return
            value = qty * price
            oc = cfg.costs.order_cost("BUY", value, adv20)
            c = oc["total"]
        cash -= value + c
        gross_traded += value
        costs_total += c
        if sym in pos:
            p = pos[sym]
            tot = p["shares"] + qty
            p["entry_px"] = (p["entry_px"] * p["shares"] + price * qty) / tot
            p["shares"] = tot
        else:
            pos[sym] = {"shares": qty, "entry_px": price, "entry_i": i, "adv20": adv20, "last_close": price, "nan_run": 0}
        trades.append({"date": dates[i], "symbol": sym, "side": "BUY", "qty": qty, "price": price,
                       "value": value, "cost": c, "participation": oc["participation"], "reason": reason, "pnl": 0.0})

    for i in range(i0, i1 + 1):
        d = dates[i]
        # 1. pending stop-loss / gate exits at the open
        for sym in list(pending_exits):
            if sym in pos:
                p_open = px(open_arr, i, sym)
                if np.isfinite(p_open) and p_open > 0:
                    sell(sym, i, p_open, "stop_loss")
                    pending_exits.discard(sym)
            else:
                pending_exits.discard(sym)
        # 2. pending rebalance at the open
        if pending_target is not None:
            tgt = pending_target
            eq_open = cash + sum(p["shares"] * (px(open_arr, i, s) if np.isfinite(px(open_arr, i, s)) else p["last_close"])
                                 for s, p in pos.items())
            for sym in list(pos):
                if sym not in tgt.index or tgt.get(sym, 0) <= 0:
                    p_open = px(open_arr, i, sym)
                    if np.isfinite(p_open) and p_open > 0:
                        sell(sym, i, p_open, "rebalance_exit")
            for sym, w in tgt.sort_values(ascending=False).items():
                if w <= 0:
                    continue
                p_open = px(open_arr, i, sym)
                if not np.isfinite(p_open) or p_open <= 0:
                    continue
                target_value = w * eq_open
                cur_value = pos[sym]["shares"] * p_open if sym in pos else 0.0
                delta = target_value - cur_value
                if sym in pos and abs(delta) / eq_open < cfg.rebalance_band:
                    continue
                if delta > 0:
                    buy(sym, i, p_open, delta, pending_adv.get(sym), "rebalance_buy")
                elif sym in pos:
                    qty = min(pos[sym]["shares"], int(-delta // p_open))
                    if qty > 0:
                        p = pos[sym]
                        value = qty * p_open
                        oc = cfg.costs.order_cost("SELL", value, p.get("adv20"))
                        c = oc["total"]
                        cash += value - c
                        gross_traded += value
                        costs_total += c
                        p["shares"] -= qty
                        trades.append({"date": d, "symbol": sym, "side": "SELL", "qty": qty, "price": p_open,
                                       "value": value, "cost": c, "participation": oc["participation"],
                                       "reason": "rebalance_trim", "pnl": (p_open - p["entry_px"]) * qty})
                        if p["shares"] <= 0:
                            pos.pop(sym)
            pending_target, pending_adv = None, {}
            n_reb += 1
        # 3. MTM, delisting watch, stop-loss marking (cash is read AFTER any forced sale)
        invested = 0.0
        for sym, p in list(pos.items()):
            c_i = px(close_arr, i, sym)
            if np.isfinite(c_i) and c_i > 0:
                p["last_close"], p["nan_run"] = c_i, 0
                if sl.stop_loss and c_i < p["entry_px"] * (1 - sl.stop_loss):
                    pending_exits.add(sym)
            else:
                p["nan_run"] += 1
                if p["nan_run"] >= cfg.delist_after_sessions:
                    sell(sym, i, p["last_close"] * (1 - cfg.delist_haircut), "delisted")
                    continue
            invested += p["shares"] * p["last_close"]
        eq = cash + invested
        equity_hist.append(eq); cash_hist.append(cash); expo_hist.append(invested / eq if eq > 0 else 0.0)
        # 4. signal at the close of a rebalance session -> execute next session
        if i in reb_pos and i < i1:
            as_of = d.date()
            key = (as_of, sl.name == "L")
            feat = feature_cache.get(key)
            if feat is None:
                feat = get_features(con, as_of, panel=panel, with_fundamentals=(sl.name == "L"),
                                    cache=cfg.reuse_features, min_turnover_inr=cfg.base_min_turnover_inr)
                feature_cache[key] = feat
            if feat is None or feat.empty:
                continue
            regime, exposure = regime_at(reg, as_of)
            sc = score(feat, sl)
            allow_new = not (sl.regime_gate and regime == "RISK_OFF")
            locked = {s_ for s_, p_ in pos.items() if i - p_["entry_i"] < sl.min_hold_sessions}
            chosen = select(sc, list(pos.keys()), sl, allow_new=allow_new, locked=locked)
            w = inverse_vol_weights(chosen, feat["vol_60"], feat["industry"], exposure, sl.cap_name, sl.cap_industry)
            pending_target = w
            pending_adv = feat["adv20_inr"].reindex(chosen).to_dict()
            holdings[str(as_of)] = {"regime": regime, "exposure": exposure, "weights": w.round(4).to_dict()}
            if progress:
                progress(f"{as_of} regime={regime} n={len(chosen)} eq={eq:,.0f}")

    idx = dates[i0:i1 + 1]
    equity = pd.Series(equity_hist, index=idx, name="equity")
    years = max(1e-9, (idx[-1] - idx[0]).days / 365.25)
    avg_eq = float(equity.mean())
    tr = pd.DataFrame(trades)
    stats = {"turnover_annual": gross_traded / 2 / avg_eq / years, "costs_total": costs_total,
             "costs_bps_annual": costs_total / avg_eq / years * 1e4, "rebalances": n_reb,
             "trades": len(trades), "final_equity": float(equity.iloc[-1]),
             "median_participation": float(tr["participation"].median()) if len(tr) else float("nan"),
             "p90_participation": float(tr["participation"].quantile(0.9)) if len(tr) else float("nan")}
    bench = _bench(con, cfg.start, cfg.end).reindex(idx).ffill()
    stats.update(summarize(equity, bench, cfg.rf_annual, stats["turnover_annual"], stats["costs_bps_annual"]))
    return BacktestResult(equity=equity, cash=pd.Series(cash_hist, index=idx), exposure=pd.Series(expo_hist, index=idx),
                          trades=tr, holdings=holdings, bench_equity=bench, stats=stats, config=cfg.to_dict())
