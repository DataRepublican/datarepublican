#!/usr/bin/env python3
"""US state SVG heatmap with real Albers outlines (not box grid).

Path data from us-atlas@3 states-albers-10m (see us_state_paths.py).
"""

from __future__ import annotations

from typing import Any

from us_state_paths import US_STATE_PATHS, US_STATE_VIEWBOX


def _color(value: float, vmax: float) -> str:
    if value <= 0 or vmax <= 0:
        return "#e5e7eb"
    t = min(1.0, value / vmax)
    # pale yellow → deep red
    r = int(254 - t * (254 - 153))
    g = int(243 - t * (243 - 27))
    b = int(200 - t * (200 - 27))
    return f"#{r:02x}{g:02x}{b:02x}"


def _fmt_heat(value: float, *, money: bool) -> str:
    if money:
        av = abs(value)
        if av >= 1_000_000_000:
            return f"${value / 1_000_000_000:,.2f}B"
        if av >= 1_000_000:
            return f"${value / 1_000_000:,.2f}M"
        if av >= 1_000:
            return f"${value:,.0f}"
        return f"${value:,.2f}"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def render_heatmap_svg(
    states: list[dict[str, Any]],
    *,
    value_key: str = "pass_clusters",
    href_template: str = "states/{state}/index.html",
    title: str = "Clusters by state",
    value_label: str = "pass clusters",
    money: bool = False,
) -> str:
    """Render a clickable US heatmap with real state outlines.

    ``states``: list of dicts with at least ``state`` and ``value_key``.
    Optional ``show_n`` is included in tooltips.
    """
    by = {str(s.get("state", "")).upper(): s for s in states}
    vmax = max((float(s.get(value_key) or 0) for s in states), default=1.0) or 1.0
    min_x, min_y, w, h = US_STATE_VIEWBOX
    # Extra headroom for title + legend
    title_h = 48
    legend_h = 28
    total_h = h + title_h + legend_h + 8

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {total_h}" '
        f'width="100%" role="img" aria-label="{title}" '
        f'style="max-width:980px;height:auto;font-family:system-ui,sans-serif;'
        f'display:block;margin:0.5rem 0 1rem">',
        f'<text x="8" y="22" font-size="16" font-weight="600" fill="#111">{title}</text>',
        f'<text x="8" y="38" font-size="11" fill="#666">'
        f"Click a state · heat = {value_label} · max {_fmt_heat(vmax, money=money)}</text>",
        f'<g transform="translate(0,{title_h})">',
    ]

    # Draw zero/missing states first so hot states paint on top at borders
    ordered = sorted(
        US_STATE_PATHS.keys(),
        key=lambda st: float(by.get(st, {}).get(value_key) or 0),
    )
    for st in ordered:
        path = US_STATE_PATHS[st]
        s = by.get(st, {"state": st, value_key: 0, "show_n": 0})
        val = float(s.get(value_key) or 0)
        show = int(s.get("show_n") or 0)
        fill = _color(val, vmax)
        tip = f"{st}: {_fmt_heat(val, money=money)} {value_label}"
        if show:
            tip += f" · {show} pages"
        if val > 0 and show > 0:
            href = href_template.format(state=st)
            parts.append(
                f'<a href="{href}">'
                f'<path d="{path}" fill="{fill}" stroke="#fff" stroke-width="1" '
                f'vector-effect="non-scaling-stroke">'
                f"<title>{tip}</title></path></a>"
            )
        else:
            parts.append(
                f'<path d="{path}" fill="{fill}" stroke="#fff" stroke-width="1" '
                f'vector-effect="non-scaling-stroke" opacity="0.85">'
                f"<title>{tip}</title></path>"
            )

    parts.append("</g>")

    # Simple legend bar
    lx, ly, lw = 8, title_h + h + 8, min(280, w - 16)
    parts.append(
        f'<defs><linearGradient id="hmleg" x1="0" x2="1" y1="0" y2="0">'
        f'<stop offset="0%" stop-color="{_color(0.01, 1)}"/>'
        f'<stop offset="100%" stop-color="{_color(1, 1)}"/>'
        f"</linearGradient></defs>"
    )
    parts.append(
        f'<rect x="{lx}" y="{ly}" width="{lw}" height="10" fill="url(#hmleg)" '
        f'stroke="#ccc" rx="2"/>'
    )
    parts.append(
        f'<text x="{lx}" y="{ly + 24}" font-size="10" fill="#666">0</text>'
        f'<text x="{lx + lw}" y="{ly + 24}" font-size="10" fill="#666" '
        f'text-anchor="end">{_fmt_heat(vmax, money=money)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
