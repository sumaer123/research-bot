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


def pillar_bars_svg(pillars: dict) -> str:
    """Generate inline SVG bars for all pillars with labels, scores, and coverage dots."""
    if not pillars:
        return ""

    lines = [f'<svg viewBox="0 0 800 300" xmlns="http://www.w3.org/2000/svg" width="100%">']
    lines.append('<style>text { font-family: system-ui; font-size: 12px; } .label { fill: #333; } .score { fill: #666; font-weight: bold; }</style>')

    y = 20
    for name, pillar_data in pillars.items():
        if not isinstance(pillar_data, dict):
            continue
        score = pillar_data.get("score", 0)
        coverage = pillar_data.get("coverage", 0)
        weight_known = pillar_data.get("weight_known", 0)

        # Pillar name and weight
        lines.append(f'<text x="10" y="{y + 15}" class="label">{name}</text>')
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
            dot_fill = "#333" if (weight_known / n_dots > i) else "#ddd"
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


def decision_onepager_md(rating: dict, feat: Optional[dict] = None, dossier: Optional[dict] = None) -> str:
    """Render the decision one-pager in Markdown format (per §4.2).
    rating: dict from latest_rating() with all JSON columns parsed
    feat: feature row dict (close, mom_12_1, dist_52w_high, dma200_ratio, etc.)
    dossier: dict with rating, confidence, catalysts if available (does not move the rating)
    """
    if not rating:
        return "# No Rating\n\nNo rating found for this symbol."

    symbol = rating.get("symbol", "?")
    name = rating.get("name", "")
    profile = rating.get("profile", "GENERAL")
    as_of = rating.get("as_of", "")
    engine_version = rating.get("engine_version", "r1")
    verdict = rating.get("rating", "NO_RATING")
    score = rating.get("score")
    mos_base = rating.get("mos_base")
    confidence = rating.get("confidence", 0)
    dci_band = rating.get("dci_band", "NONE")
    price = rating.get("price")
    fv_base = rating.get("fv_base")
    fv_bear = rating.get("fv_bear")
    fv_bull = rating.get("fv_bull")
    pillars = rating.get("pillars", {})
    gates = rating.get("gates", [])
    decision = rating.get("decision", {})
    manifest_sha = rating.get("manifest_sha", "?")
    dci_components = decision.get("confidence", {}) if decision else {}
    data_errors = rating.get("data_errors", [])

    claim_state = decision.get("claim_state", "DIAGNOSTIC") if decision else "DIAGNOSTIC"

    # Count flags by tier
    n_hard = sum(1 for g in gates if g.get("tier") == "HARD")
    n_soft = sum(1 for g in gates if g.get("tier") == "SOFT")
    n_watch = sum(1 for g in gates if g.get("tier") == "WATCH")

    lines = [
        f"# {symbol} · {name} · {profile} profile · as of {as_of} · engine {engine_version}/base",
        f"Claim state: **{claim_state}** {'(not yet calibrated)' if claim_state == 'DIAGNOSTIC' else ''}\n",
        f"## Verdict",
        f"**{verdict}** (Score {score:.0f}/100)" + (f", MoS +{mos_base:.0%}" if mos_base is not None and mos_base > 0 else
                                                       f", MoS {mos_base:.0%}" if mos_base is not None else ""),
        f"Confidence **{dci_band}** ({confidence:.2f})" + (f" · Rule {decision.get('rule_id')}" if decision and decision.get('rule_id') else ""),
    ]

    if fv_base and price:
        lines.append(f"Fair value ₹{fv_base:,.0f} (bear {fv_bear:,.0f} · base {fv_base:,.0f} · bull {fv_bull:,.0f})")
        lines.append(f"Price ₹{price:,.0f} · FV range [bear—base—bull]")

    # DCI breakdown
    if dci_components:
        dci_val = dci_components.get("dci", confidence)
        source_factor = dci_components.get("source_factor", 1.0)
        staleness_factor = dci_components.get("staleness_factor", 1.0)
        dispersion_factor = dci_components.get("dispersion_factor", 1.0)
        lines.append(f"(DCI {dci_val:.2f} = source {source_factor:.2f} × (staleness {staleness_factor:.2f} × dispersion {dispersion_factor:.2f}))")

    lines.append("\n## Pillars\n")
    pillar_lines = []
    for name, pillar_data in pillars.items():
        if not isinstance(pillar_data, dict):
            continue
        score_val = pillar_data.get("score", 0)
        weight = pillar_data.get("weight_known", 0)
        weight_total = pillar_data.get("weight_total", 1)
        coverage = pillar_data.get("coverage", 0)
        bar = _pillar_bar_text(score_val)

        # Get top 3 components
        components = pillar_data.get("components", [])
        top_comp = ", ".join(f"{c['name']} {c['raw']:.1f}" for c in sorted(
            components, key=lambda c: c.get('score', 0), reverse=True)[:3])

        pillar_lines.append(f"**{name}** [{weight:.0%}]  {bar}  {score_val:.0f}  ●●●○○  {top_comp}")

    lines.extend(pillar_lines)

    lines.append("\n## Key Moat Drivers & Top Risks\n")
    # Find top 3 moat drivers from P1
    moat_drivers = []
    if "moat_quality" in pillars and isinstance(pillars["moat_quality"], dict):
        comps = pillars["moat_quality"].get("components", [])
        moat_drivers = sorted(comps, key=lambda c: c.get('score', 0), reverse=True)[:3]

    for i, comp in enumerate(moat_drivers, 1):
        lines.append(f"* {comp.get('name', '?')}: {comp.get('raw', '?')} ({comp.get('score', 0):.0f})")

    # Top 3 risks from lowest scoring components
    all_comps = []
    for pillar_data in pillars.values():
        if isinstance(pillar_data, dict):
            all_comps.extend(pillar_data.get("components", []))

    risks = sorted([c for c in all_comps if c.get('status') == 'KNOWN'],
                   key=lambda c: c.get('score', 0))[:3]

    lines.append("\n**Top Risks:**\n")
    for i, comp in enumerate(risks, 1):
        lines.append(f"* {comp.get('name', '?')}: {comp.get('raw', '?')} ({comp.get('score', 0):.0f})")

    lines.append(f"\n## Red Flags\n")
    lines.append(f"Total: HARD {n_hard} · SOFT {n_soft} · WATCH {n_watch}")

    if gates:
        nearest_flag = None
        for g in gates:
            if g.get("tier") == "WATCH":
                nearest_flag = g
                break
        if nearest_flag:
            lines.append(f"Nearest: {nearest_flag.get('code')} at {nearest_flag.get('value')}")

    # Timing
    if feat:
        lines.append(f"\n## Timing\n")
        if feat.get("mom_12_1") is not None:
            lines.append(f"12-1m momentum: {feat.get('mom_12_1', 0):.0%}")
        if feat.get("dist_52w_high") is not None:
            lines.append(f"52w high: {feat.get('dist_52w_high', 0):.0%} below")
        if feat.get("dma200_ratio") is not None:
            lines.append(f"Above/below 200 DMA: {feat.get('dma200_ratio', 1):.2f}")

    # Dossier analyst view
    lines.append(f"\n## Analyst View (Dossier)\n")
    if dossier:
        lines.append(f"Rating: {dossier.get('rating', '?')} ({dossier.get('confidence', 0):.0%})")
        if dossier.get("catalysts"):
            lines.append(f"Catalysts: {dossier.get('catalysts')}")
    else:
        lines.append("None stored")

    # Data quality
    lines.append(f"\n## Data & Manifest\n")
    if data_errors:
        lines.append(f"Data errors: {len(data_errors)}")
    lines.append(f"Manifest SHA: {manifest_sha}")

    return "\n".join(lines)


def decision_html(rating: dict, feat: Optional[dict] = None, dossier: Optional[dict] = None) -> str:
    """Render via Jinja2 template decision.html (provided separately)."""
    # This is a placeholder; the actual template rendering happens in app.py
    md_text = decision_onepager_md(rating, feat, dossier)
    from .md import render as md_render
    return md_render(md_text)


def telegram_card(rating: dict) -> str:
    """5-line Telegram HTML card: verdict+symbol, score, MoS+FV, confidence band, top flag or 'no flags'."""
    if not rating:
        return "No rating"

    symbol = rating.get("symbol", "?")
    verdict = rating.get("rating", "NO_RATING")
    score = rating.get("score", 0)
    mos_base = rating.get("mos_base")
    fv_base = rating.get("fv_base")
    dci_band = rating.get("dci_band", "NONE")
    gates = rating.get("gates", [])

    lines = [
        f"<b>{verdict} {symbol}</b>",
        f"Score {score:.0f}/100",
        f"MoS {mos_base:.0%} · FV ₹{fv_base:,.0f}" if mos_base is not None and fv_base else "MoS ? · FV ?",
        f"Confidence <b>{dci_band}</b>",
    ]

    # Top flag
    if gates:
        top_hard = next((g for g in gates if g.get("tier") == "HARD"), None)
        top_soft = next((g for g in gates if g.get("tier") == "SOFT"), None)
        top_flag = top_hard or top_soft
        if top_flag:
            lines.append(f"🚩 {top_flag.get('code', '?')}")
        else:
            lines.append("✓ No flags")
    else:
        lines.append("✓ No flags")

    return "<br>".join(lines)
