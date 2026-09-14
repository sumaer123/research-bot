"""Split / bonus / consolidation adjustment factors.

Source of record: NSE corporate actions (subject text), each CONFIRMED against the tape —
the ex-date open must gap by roughly the implied factor versus the prior close; an
unconfirmed action is searched within +/-3 sessions and otherwise skipped and reported.
A secondary gap scan catches clean-ratio moves that persist (a split the CA feed missed).
NSE bhavcopies do NOT restate PREV_CLOSE on ex-dates (verified 2026-09-14), so the
tape alone cannot label events; the CA text + tape together can."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

import duckdb
import pandas as pd

from ..store import upsert

CLEAN_RATIOS = [1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 1 / 20, 1 / 25, 1 / 50, 2 / 3, 1 / 1.5, 2, 3, 4, 5, 10]
GAP_TOL = 0.35             # |gap / factor - 1| tolerance to confirm an action on the tape

_BONUS = re.compile(r"bonus\s*(\d+)\s*:\s*(\d+)", re.I)
_SPLIT = re.compile(r"(?:split|sub-?division).*?(?:from|of)\s*(?:rs\.?|re\.?|₹)?\s*(\d+(?:\.\d+)?)\s*/?-?.*?(?:to|into)\s*(?:rs\.?|re\.?|₹)?\s*(\d+(?:\.\d+)?)", re.I)
_CONSOL = re.compile(r"consolidat.*?(?:from|of)\s*(?:rs\.?|re\.?|₹)?\s*(\d+(?:\.\d+)?)\s*/?-?.*?(?:to|into)\s*(?:rs\.?|re\.?|₹)?\s*(\d+(?:\.\d+)?)", re.I)


def factor_from_subject(subject: str) -> Optional[tuple[float, str]]:
    s = (subject or "").strip()
    m = _BONUS.search(s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            return b / (a + b), f"bonus {a}:{b}"
    m = _SPLIT.search(s)
    if m:
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0 and new < old:
            return new / old, f"split {old:g}->{new:g}"
    m = _CONSOL.search(s)
    if m:
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0 and new > old:
            return new / old, f"consolidation {old:g}->{new:g}"
    return None


def _px(con, symbol: str, start: date, end: date) -> pd.DataFrame:
    return con.execute("""SELECT trade_date, open, close FROM prices_daily WHERE symbol = ? AND series IN ('EQ','BE')
                          AND trade_date BETWEEN ? AND ? ORDER BY trade_date""", [symbol, start, end]).df()


def _confirm(px: pd.DataFrame, ex: date, factor: float) -> Optional[tuple[date, float, float]]:
    """Find the session at/near ex where open/prev_close ~ factor. Returns (date, prior_close, gap)."""
    if px.empty or len(px) < 2:
        return None
    px = px.reset_index(drop=True)
    px["d"] = pd.to_datetime(px["trade_date"]).dt.date
    cands = []
    for i in range(1, len(px)):
        prior = px.loc[i - 1, "close"]
        op = px.loc[i, "open"]
        if not prior or not op or prior <= 0:
            continue
        gap = op / prior
        if abs(gap / factor - 1) <= GAP_TOL:
            cands.append((abs((px.loc[i, "d"] - ex).days), px.loc[i, "d"], float(prior), float(gap)))
    if not cands:
        return None
    cands.sort()
    return cands[0][1], cands[0][2], cands[0][3]


def factors_from_corporate_actions(con: duckdb.DuckDBPyConnection, start: Optional[date] = None) -> tuple[pd.DataFrame, list[dict]]:
    ca = con.execute("SELECT symbol, ex_date, subject FROM corporate_actions" + (" WHERE ex_date >= ?" if start else ""),
                     [start] if start else []).df()
    rows, skipped = [], []
    if ca.empty:
        return pd.DataFrame(), skipped
    ca["ex_date"] = pd.to_datetime(ca["ex_date"]).dt.date
    ca["parsed"] = ca["subject"].map(factor_from_subject)
    ca = ca[ca["parsed"].notna()]
    for (sym, ex), g in ca.groupby(["symbol", "ex_date"]):
        factor = 1.0
        kinds = []
        for p in g["parsed"]:
            factor *= p[0]
            kinds.append(p[1])
        if abs(factor - 1) < 1e-9:
            continue
        px = _px(con, sym, ex - timedelta(days=8), ex + timedelta(days=8))
        hit = _confirm(px, ex, factor)
        if hit is None:
            skipped.append({"symbol": sym, "ex_date": ex, "factor": factor, "kind": "; ".join(kinds), "reason": "no confirming gap on tape"})
            continue
        d, prior, gap = hit
        rows.append({"symbol": sym, "ex_date": d, "factor": factor, "prev_close_reported": prior * factor,
                     "prior_close": prior, "kind": "; ".join(kinds) + (f" [ex {ex}]" if d != ex else "") + f" gap {gap:.3f}"})
    return pd.DataFrame(rows), skipped


def factors_from_gaps(con: duckdb.DuckDBPyConnection, known: pd.DataFrame, start: Optional[date] = None) -> pd.DataFrame:
    """Clean-ratio gaps that persist for 3 sessions and have no corporate action within 5 days."""
    sql = """
      WITH px AS (
        SELECT symbol, trade_date, open, close, volume,
               lag(close) OVER w AS prior, lead(close, 3) OVER w AS c3, lead(trade_date, 3) OVER w AS d3,
               median(volume) OVER (w ROWS BETWEEN 25 PRECEDING AND 5 PRECEDING) AS vol_before,
               median(volume) OVER (w ROWS BETWEEN 5 FOLLOWING AND 25 FOLLOWING) AS vol_after
        FROM prices_daily WHERE series IN ('EQ','BE') {where}
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
      )
      SELECT symbol, trade_date AS ex_date, prior AS prior_close, open / prior AS gap, c3 / prior AS persist,
             vol_after / nullif(vol_before, 0) AS vol_ratio
      FROM px WHERE prior >= 5 AND open > 0 AND c3 > 0 AND (open / prior <= 0.7 OR open / prior >= 1.4)   -- sub-Rs5 names: tick-size artefacts
        AND d3 - trade_date <= 12
    """
    df = con.execute(sql.format(where="AND trade_date >= ?" if start else ""), [start] if start else []).df()
    if df.empty:
        return df
    df["ex_date"] = pd.to_datetime(df["ex_date"]).dt.date
    out = []
    known_keys = set(zip(known.symbol, known.ex_date)) if known is not None and not known.empty else set()
    ca = con.execute("SELECT symbol, ex_date FROM corporate_actions").df()
    ca["ex_date"] = pd.to_datetime(ca["ex_date"]).dt.date
    ca_by_sym = {s: set(g.ex_date) for s, g in ca.groupby("symbol")}
    for r in df.itertuples():
        ratio = min(CLEAN_RATIOS, key=lambda x: abs(r.gap / x - 1))
        if abs(r.gap / ratio - 1) > 0.08 or abs(r.persist / ratio - 1) > 0.25:
            continue
        # share count scales by 1/factor: traded volume must move the same way (a crash does not)
        if r.vol_ratio is None or not (r.vol_ratio == r.vol_ratio) or r.vol_ratio < 0.6 / ratio if ratio < 1 else (r.vol_ratio is None or r.vol_ratio > 1.6 / ratio):
            continue
        if (r.symbol, r.ex_date) in known_keys:
            continue
        near = any(abs((r.ex_date - d).days) <= 5 for d in ca_by_sym.get(r.symbol, ()))
        if near:
            continue
        out.append({"symbol": r.symbol, "ex_date": r.ex_date, "factor": float(ratio), "prev_close_reported": r.prior_close * ratio,
                    "prior_close": float(r.prior_close), "kind": f"gap-inferred x{ratio:.4g} (no CA record)"})
    return pd.DataFrame(out)


def refresh_factors(con: duckdb.DuckDBPyConnection, start: Optional[date] = None, with_gaps: bool = True) -> int:
    """Full replace from `start` (or everything)."""
    df, skipped = factors_from_corporate_actions(con, start)
    if with_gaps:
        extra = factors_from_gaps(con, df, start)
        if not extra.empty:
            df = pd.concat([df, extra], ignore_index=True) if not df.empty else extra
    if start:
        con.execute("DELETE FROM adj_factors WHERE ex_date >= ?", [start])
    else:
        con.execute("DELETE FROM adj_factors")
    n = upsert(con, "adj_factors", df) if not df.empty else 0
    if skipped:
        con.execute("CREATE TABLE IF NOT EXISTS factor_anomalies (symbol VARCHAR, ex_date DATE, factor DOUBLE, kind VARCHAR, reason VARCHAR, PRIMARY KEY (symbol, ex_date))")
        upsert(con, "factor_anomalies", pd.DataFrame(skipped))
    return n


def detect_factors(con: duckdb.DuckDBPyConnection, start: Optional[date] = None, symbols=None) -> pd.DataFrame:
    df, _ = factors_from_corporate_actions(con, start)
    if symbols is not None and not df.empty:
        df = df[df.symbol.isin(symbols)]
    return df
