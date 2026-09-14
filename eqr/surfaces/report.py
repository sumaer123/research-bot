"""Decision one-pager rendering: Markdown, HTML (Jinja2 + inline SVG), and Telegram card."""
from __future__ import annotations

from typing import Optional
import math


def _pillar_bar_text(score: float, width: int = 20) -> str:
    """Generate a text bar using █/░ characters for a 0-100 score."""
    if score is None or math.isnan(score):
        return "?" * width
    filled = int(round(width * score / 100))
    return "█" * filled + "░" * (width - filled)


def pillar_bars_svg(pillars: dict) -> str:  # noqa: C901
    """Generate inline SVG bars for all pillars with labels, scores, and coverage dots."""
    if not pillars:
        return ""

    lines = [f'<svg viewBox="0 0 800 300" xmlns="http://www.w3.org/2000/svg" width="100%">']
    lines.append('<style>text { font-family: system-ui; font-size: 12px; } .label { fill: #333; } .score { fill: #666; font-weight: bold; }</style>')

    y = 20
    for name, pillar_data in pillars.items():
        if not isinstance(pillar_data, dict):
            continue
        score = pillar_data.get("score") or 0
        coverage = pillar_data.get("coverage") or 0
        weight_known = pillar_data.get("weight_known", 0)

        # Pillar name and weight
        lines.append(f'<text x="10" y="{y + 15}" class="label">{PILLAR_LABELS.get(name, name)}</text>')
        lines.append(f'<text x="200" y="{y + 15}" class="score">{score:.0f}/100</text>')

        # Bar (green to red gradient based on score)
        bar_width = 300
        filled = int(bar_width * score / 100)
        hue = max(0, min(120, 120 * score / 100))  # Green (120) to Red (0)
        color = f"hsl({hue}, 70%, 50%)"
        lines.append(f'<rect x="280" y="{y + 5}" width="{filled}" height="12" fill="{color}"/>')
        lines.append(f'<rect x="{280 + filled}" y="{y + 5}" width="{bar_width - filled}" height="12" fill="#ddd"/>')

        # Coverage dots
        n_dots = 5
        dot_x_start = 600
        for i in range(n_dots):
            dot_x = dot_x_start + i * 20
            dot_fill = "#333" if (coverage * n_dots > i) else "#ddd"
            lines.append(f'<circle cx="{dot_x}" cy="{y + 11}" r="3" fill="{dot_fill}"/>')

        y += 30

    lines.append('</svg>')
    return "\n".join(lines)


def fv_range_svg(price: Optional[float], bear: Optional[float], base: Optional[float],
                 bull: Optional[float], width: int = 600, height: int = 80) -> str:
    """Generate inline SVG FV range bar with price marker (bear–base–bull)."""
    if not all([price, bear, base, bull]):
        return ""

    lo, hi = min(bear, base, bull, price), max(bear, base, bull, price)
    span = hi - lo
    if span <= 0:
        span = 1.0

    margin, bar_height = 40, 30
    total_width = width + 2 * margin

    lines = [f'<svg viewBox="0 0 {total_width} {height}" xmlns="http://www.w3.org/2000/svg" width="100%">']
    lines.append('<style>text { font-family: system-ui; font-size: 11px; } .label { fill: #666; } .price { fill: #d00; font-weight: bold; }</style>')

    # Draw range bar
    def x_pos(val):
        return margin + (val - lo) / span * width

    # Bear–base–bull zones
    bear_x = x_pos(bear)
    base_x = x_pos(base)
    bull_x = x_pos(bull)
    price_x = x_pos(price)

    # Zone colors (light to dark green)
    lines.append(f'<rect x="{bear_x}" y="30" width="{base_x - bear_x}" height="{bar_height}" fill="#90ee90" opacity="0.5"/>')
    lines.append(f'<rect x="{base_x}" y="30" width="{bull_x - base_x}" height="{bar_height}" fill="#32cd32" opacity="0.5"/>')

    # Divider lines
    for val, label in [(bear, "bear"), (base, "base"), (bull, "bull")]:
        xp = x_pos(val)
        lines.append(f'<line x1="{xp}" y1="25" x2="{xp}" y2="65" stroke="#999" stroke-width="1" stroke-dasharray="2,2"/>')
        lines.append(f'<text x="{xp - 15}" y="75" class="label">{label}</text>')

    # Price marker
    lines.append(f'<circle cx="{price_x}" cy="47" r="5" fill="none" stroke="#d00" stroke-width="2"/>')
    lines.append(f'<text x="{price_x - 10}" y="15" class="price">₹{price:,.0f}</text>')

    lines.append('</svg>')
    return "\n".join(lines)


PILLAR_LABELS = {"P1_MOAT": "Moat & quality", "P2_BALANCE": "Balance sheet", "P3_EARNINGS": "Earnings quality",
                 "P4_GROWTH": "Growth & runway", "P5_MANAGEMENT": "Management", "P6_VALUATION": "Valuation"}
VERDICT_LABEL = {"CONVICTION_BUY": "CONVICTION BUY", "SPECULATIVE_BUY": "SPECULATIVE BUY", "HOLD": "HOLD",
                 "TRIM": "TRIM / REDUCE", "SELL": "SELL / AVOID", "NO_RATING": "NO RATING"}
NEXT_RULE = [("CONVICTION_BUY", 80, 0.20), ("SPECULATIVE_BUY", 70, -0.10), ("HOLD", 50, -0.25), ("TRIM", 35, None)]


def _f(v, default=None):
    try:
        if v is None:
            return default
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def _fmt_raw(name: str, v) -> str:
    v = _f(v)
    if v is None:
        return "?"
    if any(k in name for k in ("pct", "promoter", "pledge", "payout", "cet1", "gnpa", "nnpa", "beneish_level")):
        return f"{v:.0f}" if abs(v) >= 10 else f"{v:.1f}"
    if any(k in name for k in ("spread", "roic", "roe", "roa", "margin", "yield", "growth", "gap", "cagr", "yoy", "mos",
                                "share", "conversion", "leakage", "rate", "persistence", "consistency", "dilution",
                                "cost", "nim", "trend", "delta_3y" if "days" not in name else "zzz")):
        return f"{v * 100:.1f}%"
    if "days" in name:
        return f"{v:+.0f} d"
    return f"{v:.2f}"


def _weights(profile: str, variant: str = "base") -> dict:
    try:
        from ..rating.sector import profile_weights
        return profile_weights(profile, variant)
    except Exception:                                   # noqa: BLE001
        return {}


def _dots(coverage: float) -> str:
    n = int(round(5 * max(0.0, min(1.0, coverage or 0.0))))
    return "●" * n + "○" * (5 - n)


def _components(pillar: dict) -> list[dict]:
    return [c for c in (pillar or {}).get("components", []) if isinstance(c, dict)]


def _drivers_and_risks(pillars: dict, gates: list) -> tuple[list[str], list[str]]:
    known = []
    for pname, pl in pillars.items():
        for c in _components(pl):
            if c.get("status") == "OK" and _f(c.get("score")) is not None:
                known.append((pname, c))
    drivers = sorted([k for k in known if k[0] == "P1_MOAT"], key=lambda k: -k[1]["score"])[:3]
    if len(drivers) < 3:
        drivers += sorted([k for k in known if k[0] != "P1_MOAT"], key=lambda k: -k[1]["score"])[:3 - len(drivers)]
    d_lines = [f"{c['name'].replace('_', ' ')} = {_fmt_raw(c['name'], c.get('raw'))} (score {c['score']:.0f}, {PILLAR_LABELS.get(p, p)})" for p, c in drivers]
    risks = []
    for g in gates:
        if g.get("tier") in ("HARD", "SOFT"):
            risks.append(f"{g.get('code')} ({g.get('tier')}): {g.get('evidence', '')}")
    worst = sorted(known, key=lambda k: k[1]["score"])[:5]
    for p, c in worst:
        if len(risks) >= 3:
            break
        risks.append(f"{c['name'].replace('_', ' ')} = {_fmt_raw(c['name'], c.get('raw'))} (score {c['score']:.0f}, {PILLAR_LABELS.get(p, p)})")
    return d_lines, risks[:3]


def _what_would_change(verdict: str, score, mos, price) -> list[str]:
    out = []
    score, mos = _f(score), _f(mos)
    if score is None:
        return out
    if mos is not None and price:
        if mos > -0.25:
            out.append(f"MoS below −25% (price above ₹{price / (1 + mos) * 0.75:,.0f} at the current fair value) → TRIM")
        if mos < 0.20 and verdict in ("HOLD", "SPECULATIVE_BUY"):
            out.append(f"MoS ≥ 20% (price below ₹{price / (1 + mos) / 1.20:,.0f}) with score ≥ 80 → Conviction BUY")
    if score < 80:
        out.append(f"score ≥ 80 (now {score:.0f}) with MoS ≥ 20% and no flags → Conviction BUY")
    if score >= 50:
        out.append(f"score < 50 (now {score:.0f}) → TRIM; any HARD flag → SELL")
    else:
        out.append(f"score < 35 (now {score:.0f}) → SELL")
    return out[:3]


def decision_onepager_md(rating: dict, feat: Optional[dict] = None, dossier: Optional[dict] = None) -> str:
    """The stock decision one-pager (methodology plan §4.2) as Markdown."""
    if not rating:
        return "# No rating\n\nNo rating found for this symbol."
    feat = feat or {}
    sym, name = rating.get("symbol", "?"), rating.get("name") or ""
    profile, as_of = rating.get("profile", "GENERAL"), rating.get("as_of", "")
    ev, variant = rating.get("engine_version", "r1"), rating.get("variant", "base")
    verdict = rating.get("rating") or "NO_RATING"
    score, mos, dci = _f(rating.get("score")), _f(rating.get("mos_base")), _f(rating.get("confidence"), 0.0)
    band = rating.get("dci_band") or rating.get("confidence_band") or "NONE"
    price, fvb, fvl, fvh = _f(rating.get("price")), _f(rating.get("fv_base")), _f(rating.get("fv_bear")), _f(rating.get("fv_bull"))
    dec = rating.get("decision") or {}
    conf = dec.get("confidence") or {}
    val = rating.get("valuation") or {}
    pillars = rating.get("pillars") or {}
    gates = rating.get("gates") or []
    claim = rating.get("claim_state") or "DIAGNOSTIC"
    weights = _weights(profile, variant)
    n_hard = sum(1 for g in gates if g.get("tier") == "HARD")
    n_soft = sum(1 for g in gates if g.get("tier") == "SOFT")
    n_watch = sum(1 for g in gates if g.get("tier") == "WATCH")
    md = [f"# {sym}" + (f" · {name}" if name else "") + f" · {profile} profile · as of {as_of} · engine {ev}/{variant}",
          f"Claim state: **{claim}**", "",
          f"## ▶ {VERDICT_LABEL.get(verdict, verdict)}", ""]
    if verdict == "NO_RATING":
        md += ["Data error: " + "; ".join(rating.get("data_errors") or []) or dec.get("reason", ""), ""]
    md += [f"**Score {score:.0f} / 100**" if score is not None else "**Score n/a**",
           f"**Margin of safety {mos:+.0%}**" if mos is not None else "**Margin of safety n/a**",
           f"**Confidence {band} ({dci:.2f})**" + (f" · conviction {dec.get('conviction')}" if dec.get("conviction") else ""),
           f"Rule {dec.get('rule_id') or rating.get('rule_id') or '?'}" + (f" · capped by {dec['capped_by']}" if dec.get("capped_by") else "")
           + (" · downgraded by data confidence" if dec.get("downgraded_by_confidence") else "")
           + (" · hysteresis held the previous verdict" if dec.get("hysteresis_applied") else ""), ""]
    if fvb is not None and price:
        md += [f"Fair value ₹{fvb:,.0f} (bear ₹{fvl:,.0f} · base ₹{fvb:,.0f} · bull ₹{fvh:,.0f}) · price ₹{price:,.0f}"
               if fvl is not None and fvh is not None else f"Fair value ₹{fvb:,.0f} · price ₹{price:,.0f}"]
        models = {k.replace("model_", ""): v for k, v in (val.get("models") or {}).items() if v is not None}
        if models:
            md.append("Models: " + " · ".join(f"{k} ₹{v:,.0f}" for k, v in models.items())
                      + (f" · dispersion {val['dispersion']:.0%}" if _f(val.get("dispersion")) is not None else ""))
        if _f(val.get("implied_growth")) is not None:
            md.append(f"Reverse DCF: price implies {val['implied_growth']:+.1%}/yr FCFF growth for 10y"
                      + (f" vs fundamental growth {val['fundamental_growth']:+.1%}" if _f(val.get("fundamental_growth")) is not None else "")
                      + (f" · WACC {val['wacc']:.1%}" if _f(val.get("wacc")) is not None else ""))
    if conf:
        md.append(f"DCI = (0.45×{conf.get('component_coverage', 0):.2f} coverage + 0.15×{conf.get('pillar_coverage', 0):.2f} pillars + 0.40) "
                  f"× staleness {conf.get('staleness_factor', 1):.2f} × source {conf.get('source_factor', 1):.2f} "
                  f"× dispersion {conf.get('dispersion_factor', 1):.2f} × name flags {conf.get('name_flag_factor', 1):.2f}")
    md += ["", "## Pillars (0–100, weight, coverage)", ""]
    for pname in ("P1_MOAT", "P2_BALANCE", "P3_EARNINGS", "P4_GROWTH", "P5_MANAGEMENT", "P6_VALUATION"):
        pl = pillars.get(pname) or {}
        sc = _f(pl.get("score"))
        cov = _f(pl.get("coverage"), 0.0)
        w = weights.get(pname)
        top = sorted([c for c in _components(pl) if c.get("status") == "OK"], key=lambda c: -abs(_f(c.get("score"), 50) - 50))[:3]
        detail = ", ".join(f"{c['name']} {_fmt_raw(c['name'], c.get('raw'))}" for c in top)
        md.append(f"- **{PILLAR_LABELS[pname]}** [{w:.2f}] `{_pillar_bar_text(sc)}` **{sc:.0f}** {_dots(cov)} "
                  f"{'' if pl.get('status') == 'OK' else '(UNKNOWN → prior) '}{detail}" if sc is not None and w is not None
                  else f"- **{PILLAR_LABELS[pname]}** n/a")
    drivers, risks = _drivers_and_risks(pillars, gates)
    md += ["", "## Key moat drivers", ""] + ([f"- {d}" for d in drivers] or ["- none known"])
    md += ["", "## Top 3 risks", ""] + ([f"{i + 1}. {r}" for i, r in enumerate(risks)] or ["- none identified"])
    md += ["", f"## Red flags: HARD {n_hard} · SOFT {n_soft} · WATCH {n_watch}", ""]
    md += [f"- {g.get('tier')} `{g.get('code')}` → cap {g.get('cap') or 'none'}: {g.get('evidence', '')}" for g in gates] or ["- none fired"]
    t = rating.get("timing") or dec.get("timing") or {}
    m12, d52, dma = _f(feat.get("mom_12_1", t.get("mom_12_1"))), _f(feat.get("dist_52w_high", t.get("dist_52w_high"))), _f(feat.get("dma200_ratio", t.get("dma200_ratio")))
    md += ["", "## Timing (not in the score)", "",
           "- 12-1m momentum " + (f"{m12:+.0%}" if m12 is not None else "?")
           + " · " + (f"{abs(d52):.0%} below 52w high" if d52 is not None else "52w high ?")
           + " · " + (("above" if dma >= 0 else "below") + " 200 DMA" if dma is not None else "200 DMA ?")]
    md += ["", "## What would change this", ""] + [f"- {x}" for x in _what_would_change(verdict, score, mos, price)]
    md += ["", "## Analyst view (dossier — does not move the rating)", ""]
    if dossier:
        md.append(f"- LLM view {dossier.get('rating')} · confidence {_f(dossier.get('confidence'), 0):.0%} · as of {dossier.get('as_of')}")
        for c in (dossier.get("catalysts") or [])[:3]:
            md.append(f"- catalyst: {c.get('event')} — {c.get('expected_by')} ({c.get('direction')})")
    else:
        md.append("- none stored")
    md += ["", "## Data & manifest", "",
           f"- source factor {conf.get('source_factor', '?')} · statements {feat.get('stmt_age_days', '?')} d old · "
           f"component coverage {conf.get('component_coverage', 0):.0%}"
           + (f" · name flags {', '.join(conf.get('flags', []))}" if conf.get("flags") else ""),
           f"- manifest sha `{(rating.get('manifest_sha') or '')[:16]}` · ratings row ({sym}, {as_of}, {ev}, {variant})"]
    return "\n".join(md)


def decision_html(rating: dict, feat: Optional[dict] = None, dossier: Optional[dict] = None) -> str:
    """Markdown one-pager rendered to HTML with the inline-SVG pillar bars and FV range bar on top."""
    from .md import render as md_render
    pillars = rating.get("pillars") or {}
    svg = pillar_bars_svg(pillars)
    fv = fv_range_svg(_f(rating.get("price")), _f(rating.get("fv_bear")), _f(rating.get("fv_base")), _f(rating.get("fv_bull")))
    body = md_render(decision_onepager_md(rating, feat, dossier))
    return f'<div class="decision-svg">{fv}</div><div class="pillar-svg">{svg}</div>{body}'


def telegram_card(rating: dict) -> str:
    """5-line Telegram HTML card (newline separated; Telegram HTML has no <br>)."""
    if not rating:
        return "No rating"
    sym, verdict = rating.get("symbol", "?"), rating.get("rating") or "NO_RATING"
    score, mos, fvb = _f(rating.get("score")), _f(rating.get("mos_base")), _f(rating.get("fv_base"))
    band = rating.get("dci_band") or rating.get("confidence_band") or "NONE"
    gates = rating.get("gates") or []
    top = next((g for g in gates if g.get("tier") == "HARD"), None) or next((g for g in gates if g.get("tier") == "SOFT"), None)
    lines = [f"<b>{VERDICT_LABEL.get(verdict, verdict)} · {sym}</b>",
             f"Score {score:.0f}/100" if score is not None else "Score n/a",
             f"MoS {mos:+.0%} · FV ₹{fvb:,.0f}" if mos is not None and fvb else "MoS n/a",
             f"Confidence {band}",
             f"🚩 {top.get('code')}" if top else "✓ no red flags"]
    return "\n".join(lines)
