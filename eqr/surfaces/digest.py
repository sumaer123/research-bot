"""Daily digest: regime, sleeve entries/exits, results due today, quality failures."""
from __future__ import annotations

import html
from datetime import date, timedelta

from . import queries as q


def build_digest(con, today: date | None = None) -> str:
    today = today or date.today()
    fr = q.freshness(con)
    reg = q.regime_now(con)
    lines = [f"<b>eqr digest — {today}</b>"]
    if reg:
        lines.append(f"Regime: <b>{reg['regime']}</b> (exposure {reg['exposure']:.0%}) · NIFTY 500 {reg['nifty500']:,.0f} · VIX {reg['vix']:.1f}")
    lines.append(f"Data: last session {fr['last_session']} · features {fr['last_features']}")
    fails = fr["quality"][fr["quality"].status == "FAIL"] if len(fr["quality"]) else []
    if len(fails):
        lines.append("⚠️ Quality: " + "; ".join(f"{r.check_name} ({html.escape(str(r.detail))})" for r in fails.itertuples()))
    for sl in ("L", "S"):
        ch = q.rank_changes(con, sl)
        tbl = q.latest_ranks(con, sl)
        if tbl.empty:
            continue
        v = con.execute("SELECT verdict FROM backtests WHERE sleeve = ? AND verdict IN ('VALIDATED','NOT VALIDATED') "
                        "ORDER BY created_at DESC LIMIT 1", [sl]).fetchone()
        tag = {"VALIDATED": "validated", "NOT VALIDATED": "NOT validated — diagnostic only"}.get(v[0] if v else "", "unvalidated")
        lines.append(f"\n<b>Sleeve {sl}</b> ({tag}) as of {ch['as_of']}: {len(tbl)} names")
        if ch["entries"]:
            lines.append("  ↑ in: " + ", ".join(ch["entries"]))
        if ch["exits"]:
            lines.append("  ↓ out: " + ", ".join(ch["exits"]))
        top = ", ".join(f"{r.symbol} ({r.weight:.1%})" for r in tbl.head(8).itertuples())
        lines.append("  top: " + top)
    due = con.execute("""SELECT DISTINCT r.symbol FROM results_calendar r
                         JOIN ranks k ON k.symbol = r.symbol AND k.weight > 0
                         WHERE k.as_of = (SELECT max(as_of) FROM ranks) AND r.filing_dt::DATE BETWEEN ? AND ?
                         ORDER BY 1""", [today - timedelta(days=1), today]).fetchall()
    if due:
        lines.append("\nResults filed in the last day for held names: " + ", ".join(r[0] for r in due))
    return "\n".join(lines)
