"""The timeline picture: error ratio, budget spent, incidents and each
rule's alerts, on one time axis."""

from __future__ import annotations

import math
from html import escape

from .incidents import Incident
from .score import RuleResult
from .series import Series
from .timeutil import format_time

# Categorical slots in fixed order (one per rule); status colours are not used
# for series.
RULE_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
INK, MUTED, GRID = "#24292f", "#57606a", "#d8dee4"
SMOOTH = 10  # minutes
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def timeline(
    series: Series,
    incidents: list[Incident],
    results: list[RuleResult],
    target: float,
    budget_events: float,
    start: int,
    end: int,
    title: str,
) -> str:
    W, left, right = 1000.0, 150.0, 24.0
    pw = W - left - right
    top = 70.0
    ratio_h, budget_h, lane_h, gap = 150.0, 70.0, 26.0, 36.0
    y_ratio = top
    y_budget = y_ratio + ratio_h + gap
    y_lanes = y_budget + budget_h + gap
    lanes = 1 + len(results)
    H = y_lanes + lanes * lane_h + 90

    def x(ts: float) -> float:
        return left + (ts - start) / (end - start) * pw

    o: list[str] = []
    a = o.append
    a(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT}">'
    )
    a('<rect width="100%" height="100%" fill="#ffffff"/>')
    a(f'<text x="24" y="30" font-size="17" font-weight="600" fill="{INK}">{escape(title)}</text>')
    a(
        f'<text x="24" y="50" font-size="12.5" fill="{MUTED}">{format_time(start)} to {format_time(end)} UTC. '
        f"Error ratio (over at least 10 minutes), error budget spent, and when each rule would have paged.</text>"
    )

    # Vertical time grid, under everything else.
    span_s = end - start
    step = next(s for s in (3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400, 2 * 86400, 7 * 86400) if span_s / s <= 10)
    ticks = list(range((start // step + 1) * step, end, step))
    y_bottom = y_lanes + lanes * lane_h + 6
    for t in ticks:
        a(
            f'<line x1="{x(t):.1f}" y1="{y_ratio}" x2="{x(t):.1f}" y2="{y_bottom:.1f}" stroke="{GRID}" stroke-dasharray="2 3"/>'
        )

    # Panel 1: error ratio, log scale, one value per pixel-wide bucket.
    lo_exp, hi_exp = -5, 0

    def yr(r: float) -> float:
        e = math.log10(max(r, 10.0**lo_exp))
        return y_ratio + ratio_h - (e - lo_exp) / (hi_exp - lo_exp) * ratio_h

    for e in range(lo_exp, hi_exp + 1):
        yy = yr(10.0**e)
        a(f'<line x1="{left}" y1="{yy:.1f}" x2="{left + pw}" y2="{yy:.1f}" stroke="{GRID}"/>')
        label = f"{100 * 10.0**e:g}%"
        a(f'<text x="{left - 8}" y="{yy + 4:.1f}" font-size="11" text-anchor="end" fill="{MUTED}">{label}</text>')
    a(f'<text x="24" y="{y_ratio + ratio_h / 2:.1f}" font-size="12" font-weight="600" fill="{INK}">error ratio</text>')
    budget_rate = 1 - target
    yb = yr(budget_rate)
    a(f'<line x1="{left}" y1="{yb:.1f}" x2="{left + pw}" y2="{yb:.1f}" stroke="{INK}" stroke-dasharray="5 3"/>')
    a(
        f'<text x="{left + pw - 4}" y="{yb - 5:.1f}" font-size="11" text-anchor="end" fill="{INK}">budget rate (1x): {100 * budget_rate:g}%</text>'
    )

    buckets = int(pw)
    i0, i1 = series.index(start), series.index(end)
    pts = []
    for b in range(buckets):
        ba = i0 + (i1 - i0) * b // buckets
        bb = max(ba + 1, i0 + (i1 - i0) * (b + 1) // buckets)
        # At least SMOOTH minutes per point, so a quiet minute with no errors
        # does not read as a plunge on the log scale.
        r = series.ratio(min(ba, bb - SMOOTH), bb)
        if r is not None:
            pts.append(f"{left + b + 0.5:.1f},{yr(r):.1f}")
    if pts:
        a(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{INK}" stroke-width="1.2"/>')

    # Panel 2: budget spent since the start of the view.
    total_bad = series.bad_in(i0, i1)
    top_pct = max(5.0, math.ceil(100 * total_bad / budget_events / 10) * 10) if budget_events else 5.0

    def yu(pct: float) -> float:
        return y_budget + budget_h - pct / top_pct * budget_h

    for pct in (0, top_pct / 2, top_pct):
        a(f'<line x1="{left}" y1="{yu(pct):.1f}" x2="{left + pw}" y2="{yu(pct):.1f}" stroke="{GRID}"/>')
        a(f'<text x="{left - 8}" y="{yu(pct) + 4:.1f}" font-size="11" text-anchor="end" fill="{MUTED}">{pct:g}%</text>')
    a(
        f'<text x="24" y="{y_budget + budget_h / 2 - 6:.1f}" font-size="12" font-weight="600" fill="{INK}">budget spent</text>'
    )
    a(
        f'<text x="24" y="{y_budget + budget_h / 2 + 9:.1f}" font-size="11" fill="{MUTED}">of 30 days&#x2019; budget</text>'
    )
    cum, pts = 0, []
    for b in range(buckets):
        ba = i0 + (i1 - i0) * b // buckets
        bb = max(ba + 1, i0 + (i1 - i0) * (b + 1) // buckets)
        cum += series.bad_in(ba, bb)
        pts.append(f"{left + b + 0.5:.1f},{yu(100 * cum / budget_events if budget_events else 0):.1f}")
    a(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{INK}" stroke-width="1.5"/>')

    # Panel 3: incidents, then one lane per rule.
    def lane_y(k: int) -> float:
        return y_lanes + k * lane_h

    def span(x0: float, x1: float, y: float, h: float, fill: str, extra: str = "") -> None:
        x0, x1 = max(x0, left), min(x1, left + pw)
        if x1 > x0 - 2:
            a(
                f'<rect x="{x0:.1f}" y="{y:.1f}" width="{max(x1 - x0, 2.5):.1f}" height="{h:.1f}" fill="{fill}" {extra}/>'
            )

    a(
        f'<text x="{left - 10}" y="{lane_y(0) + lane_h / 2 + 2:.1f}" font-size="12" font-weight="600" text-anchor="end" fill="{INK}">incidents</text>'
    )
    for inc in incidents:
        if inc.end < start or inc.start > end:
            continue
        fill = "#57606a" if inc.pages else "#afb8c1"
        span(x(inc.start), x(inc.end), lane_y(0) + 5, lane_h - 12, fill)
        a(
            f'<text x="{max(x(inc.start), left) + 1:.1f}" y="{lane_y(0) + 1:.1f}" font-size="10" fill="{MUTED}">{escape(inc.name)}</text>'
        )
    for k, rr in enumerate(results, start=1):
        colour = RULE_COLOURS[(k - 1) % len(RULE_COLOURS)]
        y = lane_y(k)
        a(
            f'<text x="{left - 10}" y="{y + lane_h / 2 + 2:.1f}" font-size="12" font-weight="600" text-anchor="end" fill="{INK}">{escape(rr.rule.name)}</text>'
        )
        a(f'<line x1="{left}" y1="{y + lane_h / 2:.1f}" x2="{left + pw}" y2="{y + lane_h / 2:.1f}" stroke="{GRID}"/>')
        for al in rr.alerts:
            stop = series.end if al.resolved is None else al.resolved
            if stop < start or al.fired > end:
                continue
            span(x(al.fired), x(stop), y + 6, lane_h - 14, colour)
        # Page markers: true pages need nothing more; false and late are labelled.
        for al in rr.false_pages + rr.late_pages:
            if start <= al.fired <= end:
                tag = "false" if al in rr.false_pages else "late"
                xx = x(al.fired)
                a(f'<path d="M{xx:.1f},{y + 3:.1f} l-4,-7 h8 z" fill="#ffffff" stroke="{INK}" stroke-width="1.2"/>')
                a(f'<text x="{xx + 6:.1f}" y="{y - 0:.1f}" font-size="10" fill="{INK}">{tag}</text>')

    # Time labels (the grid lines were drawn first, under everything).
    y_axis = lane_y(lanes) + 14
    for t in ticks:
        label = format_time(t)[5:] if step < 86400 else format_time(t)[5:10]
        a(
            f'<text x="{x(t):.1f}" y="{y_axis + 4:.1f}" font-size="11" text-anchor="middle" fill="{MUTED}">{label}</text>'
        )

    ly = y_axis + 36
    lx = left

    def item(sw: str, label: str) -> None:
        nonlocal lx
        a(f'<g transform="translate({lx:.1f},{ly - 6:.1f})">{sw}</g>')
        a(f'<text x="{lx + 30:.1f}" y="{ly + 4:.1f}" font-size="12" fill="{MUTED}">{escape(label)}</text>')
        lx += 30 + 6.6 * len(label) + 22

    item('<rect y="2" width="22" height="9" fill="#57606a"/>', "incident (page)")
    item('<rect y="2" width="22" height="9" fill="#afb8c1"/>', "incident (ticket)")
    item(f'<rect y="2" width="22" height="9" fill="{RULE_COLOURS[0]}"/>', "rule firing (a colour per rule)")
    item(
        f'<path d="M11,10 l-4,-7 h8 z" fill="#ffffff" stroke="{INK}" stroke-width="1.2"/>',
        "page with no open incident (false, or late)",
    )
    a("</svg>")
    return "\n".join(o) + "\n"
