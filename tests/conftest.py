import os
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("EQR_DATA_DIR", str(tmp_path / "data"))
    # network safety: web research is OFF by default in tests so run_dossier's auto-web step is a
    # no-op DISABLED. Tests that exercise the enabled path set EQR_PARALLEL_ENABLED=1 themselves.
    monkeypatch.setenv("EQR_PARALLEL_ENABLED", "0")
    from eqr.store import connect
    con = connect(tmp_path / "data" / "eqr.duckdb")      # same path settings() resolves to
    yield con
    con.close()


FIXTURES = Path(__file__).parent / "fixtures"


def make_synthetic_market(con, n_symbols=40, n_days=600, seed=0, start=None, planted=None):
    """Random-walk EQ prices for n_symbols over n_days weekdays, NIFTY 500 index, instruments,
    annual+quarterly statements for every symbol, a 1:2 split for S01 at day 300.
    `planted` = dict(symbol -> daily drift) to plant a recoverable signal."""
    import numpy as np
    import pandas as pd
    from datetime import date, timedelta, datetime
    from eqr.store import upsert
    rng = np.random.default_rng(seed)
    start = start or date(2020, 1, 1)
    days = pd.bdate_range(start, periods=n_days)
    syms = [f"S{i:02d}" for i in range(1, n_symbols + 1)]
    rows, idx_rows = [], []
    bench = 10000.0
    for j, sym in enumerate(syms):
        px = 100.0 + 10 * j
        drift = (planted or {}).get(sym, 0.0)
        for i, d in enumerate(days):
            r = rng.normal(drift, 0.02)
            prev = px
            px = max(1.0, px * (1 + r))
            prev_close = prev
            open_px = prev_close * (1 + rng.normal(0, 0.005))
            if sym == "S01" and i == 300:              # 1:1 bonus: open gaps to half; prev_close stays raw (as NSE does)
                px, open_px = px / 2, open_px / 2
            hi, lo = px * (1 + abs(rng.normal(0, 0.01))), px * (1 - abs(rng.normal(0, 0.01)))
            vol = int(1e5 * (1 + j) * (2 if sym == "S01" and i > 300 else 1))
            rows.append({"trade_date": d.date(), "symbol": sym, "series": "EQ", "isin": f"INE{j:04d}",
                         "prev_close": prev_close, "open": open_px,
                         "high": hi, "low": lo, "close": px, "last": px, "vwap": px, "volume": vol,
                         "turnover_inr": vol * px, "trades": 1000, "deliv_qty": vol // 2,
                         "deliv_pct": 50 + rng.normal(0, 5), "source": "synthetic"})
    for d in days:
        bench *= 1 + rng.normal(0.0003, 0.01)
        idx_rows.append({"trade_date": d.date(), "index_name": "Nifty 500", "close": bench, "pe": 20.0})
        idx_rows.append({"trade_date": d.date(), "index_name": "Nifty 50", "close": bench * 1.1})
        idx_rows.append({"trade_date": d.date(), "index_name": "India VIX", "close": 15 + rng.normal(0, 2)})
    upsert(con, "prices_daily", pd.DataFrame(rows))
    upsert(con, "index_daily", pd.DataFrame(idx_rows))
    con.execute("INSERT OR REPLACE INTO corporate_actions VALUES (?, ?, ?, ?, ?, ?, ?)",
                ["S01", days[300].date(), "Bonus 1:1", days[300].date(), 10.0, "EQ", datetime.now()])
    con.executemany("INSERT OR REPLACE INTO trading_days VALUES (?, ?, ?, ?)",
                    [[d.date(), n_symbols, "synthetic", datetime.now()] for d in days])
    inst = pd.DataFrame({"symbol": syms, "name": syms, "series": "EQ", "face_value": 10.0,
                         "industry": [f"IND{j % 3}" for j in range(n_symbols)], "as_of": days[-1].date()})
    upsert(con, "instruments", inst)
    # statements: 4 fiscal years + 8 quarters per symbol, visible 60 days after period end
    st = []
    for j, sym in enumerate(syms):
        base = 1000.0 * (1 + j)
        for k, fy in enumerate([date(2018, 3, 31), date(2019, 3, 31), date(2020, 3, 31), date(2021, 3, 31)]):
            g = 1.1 ** k
            for stmt, item, v in [("pl_a", "sales", base * g), ("pl_a", "net_profit", base * g * 0.1),
                                  ("pl_a", "operating_profit", base * g * 0.2), ("pl_a", "depreciation", base * g * 0.03),
                                  ("pl_a", "other_income", base * g * 0.01), ("pl_a", "interest", base * g * 0.02),
                                  ("pl_a", "dividend_payout_pct", 20.0),
                                  ("bs_a", "equity_capital", 100.0), ("bs_a", "reserves", base * 0.5 * g),
                                  ("bs_a", "borrowings", base * 0.3), ("bs_a", "other_liabilities", base * 0.2),
                                  ("bs_a", "total_assets", base * 1.2 * g), ("bs_a", "other_assets", base * 0.4),
                                  ("cf_a", "cash_from_operating_activity", base * g * 0.12),
                                  ("cf_a", "free_cash_flow", base * g * 0.08), ("ratios_a", "roce_pct", 15.0 + j % 5)]:
                st.append({"symbol": sym, "basis": "consolidated", "stmt": stmt, "period_end": fy,
                           "line_item": item, "value": v, "fetched_at": datetime.now(),
                           "visible_from": fy + timedelta(days=60)})
        qe = [date(2019, 6, 30), date(2019, 9, 30), date(2019, 12, 31), date(2020, 3, 31),
              date(2020, 6, 30), date(2020, 9, 30), date(2020, 12, 31), date(2021, 3, 31)]
        for k, pe in enumerate(qe):
            g = 1.03 ** k
            for item, v in [("sales", base / 4 * g), ("net_profit", base / 4 * g * 0.1), ("operating_profit", base / 4 * g * 0.2),
                            ("depreciation", base / 4 * g * 0.03), ("other_income", base / 4 * g * 0.01),
                            ("interest", base / 4 * g * 0.02), ("eps_in_rs", 2.5 * g)]:
                st.append({"symbol": sym, "basis": "consolidated", "stmt": "pl_q", "period_end": pe,
                           "line_item": item, "value": v, "fetched_at": datetime.now(),
                           "visible_from": pe + timedelta(days=45)})
        for k, pe in enumerate(qe):
            for holder, v in [("promoters", 50 + k * 0.5), ("fii", 10.0), ("dii", 5 + k * 0.2)]:
                st.append(None)
                st.pop()
                con.execute("INSERT OR REPLACE INTO shareholding VALUES (?, ?, ?, ?, ?, ?)",
                            [sym, pe, holder, v, datetime.now(), pe + timedelta(days=21)])
    upsert(con, "statements", pd.DataFrame(st))
    return syms, days
