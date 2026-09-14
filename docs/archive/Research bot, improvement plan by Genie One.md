# IMPROVEMENT_PLAN.md — Prioritised Action Plan

**Repository:** `sumaer123/research-bot` (`eqr`)  
**Companion to:** `REVIEW.md` (same branch)  
**Prioritisation:** Correctness of research claims first, operational reliability second, code elegance last.

---

## Phase 1: Protect the Validated Claim (weeks 1-2)

These items directly affect whether the Sleeve L VALIDATED verdict is trustworthy.

### 1.1 Close the Survivorship Gap (open item #1)

**Priority:** Highest. The single largest threat to the claim.  
**Effort:** ~2-3 days of data work.  
**Action:**
- Fetch statements for ~450 delisted names via BSE code (screener.in may not have pages for delisted names; fallback to BSE corporate filings or archived screener pages).
- Backfill `statements` with `visible_from` set to the filing date or the +45/+60 day rule.
- Re-run `eqr validate L` and compare the CAGR, Sharpe, and IR with the current numbers.
- If the results change by more than 200 bps CAGR or 0.1 Sharpe, update the claim.

### 1.2 Verify Panel Adjustment Materiality (F-01)

**Priority:** High. Probably benign but needs confirmation.  
**Effort:** ~1 hour.  
**Action:**
```bash
# Run the standard backtest
eqr validate L --start 2017-06-01 --end 2026-09-11

# Then modify panel.py to reload the panel at each rebalance (slow mode):
# In backtest.py, inside the rebalance branch (line ~222), add:
#   panel = load_panel(con, window_start(as_of, 420), as_of, series=("EQ","BE","BZ"))
# This makes every feature computation use a panel adjusted only up to as_of.
# Compare the equity curves. If they differ by < 50 bps CAGR, the finding is benign.
```

### 1.3 Add PIT Test for `statements_as_of` (F-16)

**Priority:** High. A PIT violation would be the highest-impact bug class; a test costs 10 lines.  
**Effort:** 15 minutes.  
**Action:** Add to `tests/test_store.py`:
```python
def test_statements_as_of_hides_future(tmp_db):
    from datetime import date, timedelta, datetime
    from eqr.store import upsert
    from eqr.store.pit import statements_as_of
    import pandas as pd
    upsert(tmp_db, "statements", pd.DataFrame([
        {"symbol": "TEST", "basis": "consolidated", "stmt": "pl_q",
         "period_end": date(2023, 6, 30), "line_item": "sales",
         "value": 100.0, "fetched_at": datetime.now(),
         "visible_from": date(2023, 9, 15)}]))
    # Before visible_from: hidden
    assert statements_as_of(tmp_db, date(2023, 9, 14), ["TEST"]).empty
    # On visible_from: visible
    assert len(statements_as_of(tmp_db, date(2023, 9, 15), ["TEST"])) == 1
```

---

## Phase 2: Operational Hardening (weeks 2-3)

### 2.1 Add CI (F-12)

**Priority:** Highest-leverage ops improvement.  
**Effort:** 30 minutes.  
**Action:** Create `.github/workflows/test.yml`:
```yaml
name: test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v4
    - run: uv venv --python 3.13 .venv
    - run: uv pip install --python .venv/bin/python -e '.[dev]'
    - run: .venv/bin/python -m pytest --cov=eqr --cov-fail-under=60
```

### 2.2 Fix Token Timing Side-Channel (F-08)

**Priority:** High. One-line fix.  
**Effort:** 2 minutes.  
**Action:** In `eqr/surfaces/web/app.py:92`, replace:
```python
if auth != f"Bearer {token}":
```
with:
```python
import hmac
if not hmac.compare_digest(auth, f"Bearer {token}"):
```

### 2.3 Configure Telegram Alerting (F-14)

**Priority:** Medium. The only alerting channel is dead.  
**Effort:** 10 minutes.  
**Action:** Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Test with `eqr digest --send`.

### 2.4 Implement the Quality Gate on Backtests

**Priority:** Medium. Spec §10 says it exists; it does not.  
**Effort:** 30 minutes.  
**Action:** At the top of `run_backtest` in `backtest.py`, add a check:
```python
if not force:
    fails = con.execute("""
        SELECT count(*) FROM quality_checks
        WHERE as_of BETWEEN ? AND ? AND status = 'FAIL'
    """, [cfg.start, cfg.end]).fetchone()[0]
    if fails > 0:
        raise ValueError(f"{fails} quality failures in [{cfg.start}, {cfg.end}]; use --force to override")
```

---

## Phase 3: Code Hygiene (weeks 3-4)

### 3.1 Remove `yfinance` Dependency (F-17)

Delete `"yfinance>=0.2"` from `pyproject.toml:15`.

### 3.2 Pin Dependencies (F-18)

Run `uv pip compile pyproject.toml -o requirements.lock` and commit the lock file. Add a CI step that checks `uv pip install -r requirements.lock` succeeds.

### 3.3 Add PIT Gating to `instruments` (F-02)

Add `visible_from` to the `instruments` table. Populate it with the `as_of` date. Modify `build.py:37` to filter `WHERE as_of <= ?`. This requires a schema migration (a one-time `ALTER TABLE instruments ADD COLUMN visible_from DATE`).

### 3.4 Sanitise `md_render` Output (F-09)

Use `bleach` or `nh3` to strip dangerous HTML tags from rendered markdown before passing to templates with `|safe`.

### 3.5 Restrict `.env` Permissions (F-11)

In both install scripts, after copying `.env.example` to `.env`, add `chmod 600 .env`.

### 3.6 Add `ruff` Configuration

Add to `pyproject.toml`:
```toml
[tool.ruff]
target-version = "py313"
select = ["E", "F", "W", "I", "UP", "B", "SIM"]
```

---

## Phase 4: Future Research (after Phase 1-3)

### 4.1 Sleeve S Redesign (open item #2)

Wait until the survivorship gap is closed and the Sleeve L claim is re-verified. Then run the pre-registered 8-12 week hold experiment for Sleeve S.

### 4.2 Advisor API Hardening

Not needed until Project Upstox R6 integration begins. When the time comes:
- Add rate limiting (e.g. `slowapi`).
- Add request logging.
- Add a `stale_after` timestamp so the client knows when to stop trusting cached evidence.

### 4.3 VM Provisioning (open item #3)

Defer until the Mac setup proves unreliable or until the advisor API needs to be accessible from the OCI box. The systemd units are ready but untested.

---

## Decision Log

| Decision | Rationale |
|---|---|
| Survivorship gap first | Directly threatens the one validated claim; everything else is secondary |
| CI before VM | 30 min of work that catches regressions on every push; the VM is weeks away |
| Token fix before Telegram | A secret leak is worse than a missing alert |
| Skip Sleeve S redesign for now | It is already NOT VALIDATED; no claim at risk |
| Skip linter/formatter | Low impact; can be added whenever convenient |
