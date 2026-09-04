#!/usr/bin/env python3
"""Build master_index.html linking every report suite index.html under reports/."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPORTS = SCRIPT_DIR / "reports"
OUT_NAME = "master_index.html"

# Suite name patterns → (kind, focus, slice, geography)
# national: {focus?}_{slice}_clusters_YYYY-MM-DD  or  {slice}_clusters_...
# by-state: {focus}_{slice}_by_state_YYYY-MM-DD

FOCUS_LABELS = {
    "dot": "DOT / trucking",
    "medicare": "Medicare / NPPES",
    "fec": "FEC political money",
    "fec_committee": "FEC committee × other types",
    "contractor": "990 contractors",
    "grants": "NGO Grants (incoming)",
    "grants_out": "NGO Grants (outgoing)",
    "usg": "USG NGO Funding",
}

# Longer focus tokens first so grants_out is not parsed as grants + "out".
_FOCUS_ALT = "fec_committee|grants_out|dot|medicare|fec|contractor|grants|usg"

SLICE_LABELS = {
    "address": "Address",
    "colocator": "Colocator",
    "loose_colocator": "Loose colocator (0.5°)",
    "zipcode": "Zip code",
    "colocator_ll": "Colocator (LL: only)",
}

SKIP_DIR_PREFIXES = (
    "smoke_",
    "colocator_smoke",
    "address_smoke",
)


def parse_suite(name: str) -> dict | None:
    if any(name.startswith(p) for p in SKIP_DIR_PREFIXES):
        return None
    if name in ("data", "providers") or name.startswith("."):
        return None

    # Stable (undated) paths preferred for public deploy — day="" sorts as live.
    m = re.match(
        rf"^(?P<focus>{_FOCUS_ALT})_"
        r"(?P<slice>address|colocator|loose_colocator|zipcode|colocator_ll)"
        r"_by_state$",
        name,
    )
    if m:
        return {
            "name": name,
            "geo": "by_state",
            "focus": m.group("focus"),
            "slice": m.group("slice"),
            "day": "",
        }

    m = re.match(
        rf"^(?P<focus>{_FOCUS_ALT})_"
        r"(?P<slice>address|colocator|loose_colocator|zipcode|colocator_ll)"
        r"_clusters$",
        name,
    )
    if m:
        return {
            "name": name,
            "geo": "national",
            "focus": m.group("focus"),
            "slice": m.group("slice"),
            "day": "",
        }

    m = re.match(
        r"^(?P<slice>address|colocator|loose_colocator|zipcode|colocator_ll)"
        r"_clusters$",
        name,
    )
    if m:
        return {
            "name": name,
            "geo": "national",
            "focus": "dot",
            "slice": m.group("slice"),
            "day": "",
        }

    m = re.match(
        rf"^(?P<focus>{_FOCUS_ALT})_"
        r"(?P<slice>address|colocator|loose_colocator|zipcode|colocator_ll)"
        r"_by_state_(?P<day>\d{4}-\d{2}-\d{2})$",
        name,
    )
    if m:
        return {
            "name": name,
            "geo": "by_state",
            "focus": m.group("focus"),
            "slice": m.group("slice"),
            "day": m.group("day"),
        }

    m = re.match(
        rf"^(?P<focus>{_FOCUS_ALT})_"
        r"(?P<slice>address|colocator|loose_colocator|zipcode|colocator_ll)"
        r"_clusters_(?P<day>\d{4}-\d{2}-\d{2})$",
        name,
    )
    if m:
        return {
            "name": name,
            "geo": "national",
            "focus": m.group("focus"),
            "slice": m.group("slice"),
            "day": m.group("day"),
        }

    # Trucking national: address_clusters_..., colocator_clusters_...
    m = re.match(
        r"^(?P<slice>address|colocator|loose_colocator|zipcode|colocator_ll)"
        r"_clusters_(?P<day>\d{4}-\d{2}-\d{2})$",
        name,
    )
    if m:
        return {
            "name": name,
            "geo": "national",
            "focus": "dot",
            "slice": m.group("slice"),
            "day": m.group("day"),
        }

    return None


def collect_suites(reports_dir: Path) -> list[dict]:
    suites: list[dict] = []
    if not reports_dir.is_dir():
        return suites
    for child in sorted(reports_dir.iterdir()):
        if not child.is_dir():
            continue
        meta = parse_suite(child.name)
        if not meta:
            continue
        index = child / "index.html"
        if not index.exists():
            meta["ready"] = False
            meta["href"] = None
            meta["mtime"] = None
        else:
            meta["ready"] = True
            meta["href"] = f"{child.name}/index.html"
            meta["mtime"] = datetime.fromtimestamp(index.stat().st_mtime)
            # rough size signals
            states_dir = child / "states"
            if states_dir.is_dir():
                meta["n_states"] = sum(1 for p in states_dir.iterdir() if p.is_dir())
            else:
                meta["n_states"] = 0
            meta["n_html"] = sum(1 for _ in child.rglob("*.html"))
        suites.append(meta)
    return suites


def pick_latest(suites: list[dict]) -> list[dict]:
    """Prefer undated (live) suite, else newest dated day, per (geo, focus, slice)."""
    best: dict[tuple, dict] = {}
    for s in suites:
        key = (s["geo"], s["focus"], s["slice"])
        cur = best.get(key)
        if cur is None:
            best[key] = s
            continue
        s_day = s.get("day") or ""
        c_day = cur.get("day") or ""
        # Undated (live deploy path) always wins over dated archives
        if s_day == "" and c_day != "":
            best[key] = s
        elif c_day == "" and s_day != "":
            continue
        elif s_day > c_day or (
            s_day == c_day and s.get("ready") and not cur.get("ready")
        ):
            best[key] = s
    return sorted(
        best.values(),
        key=lambda s: (s["geo"], s["focus"], s["slice"]),
    )


def render_html(suites: list[dict], *, all_suites: list[dict], reports_dir: Path) -> str:
    generated = datetime.now().isoformat(timespec="seconds")
    focuses = ["dot", "medicare", "fec", "contractor", "grants", "grants_out", "usg"]
    slices = ["colocator", "zipcode", "loose_colocator", "address"]
    geos = [("national", "National clusters"), ("by_state", "By-state maps & details")]

    by_key = {(s["geo"], s["focus"], s["slice"]): s for s in suites}

    def cell(geo: str, focus: str, slice_by: str) -> str:
        s = by_key.get((geo, focus, slice_by))
        if not s:
            return '<td class="miss">—</td>'
        if not s.get("ready"):
            return f'<td class="pending" title="{s["name"]}">…</td>'
        extra = ""
        if geo == "by_state" and s.get("n_states"):
            extra = f'<div class="sub">{s["n_states"]} states · {s.get("n_html", 0)} html</div>'
        elif s.get("n_html"):
            extra = f'<div class="sub">{s["n_html"]} html</div>'
        mtime = s["mtime"].strftime("%Y-%m-%d %H:%M") if s.get("mtime") else ""
        day_lbl = s["day"] if s.get("day") else "live"
        return (
            f'<td class="ok">'
            f'<a href="{s["href"]}">{SLICE_LABELS.get(slice_by, slice_by)}</a>'
            f'{extra}<div class="sub">{day_lbl} · {mtime}</div></td>'
        )

    sections = []
    for geo, geo_label in geos:
        rows = []
        for focus in focuses:
            cells = "".join(cell(geo, focus, sl) for sl in slices)
            rows.append(
                f"<tr><th>{FOCUS_LABELS.get(focus, focus)}</th>{cells}</tr>"
            )
        slice_headers = "".join(
            f"<th>{SLICE_LABELS.get(sl, sl)}</th>" for sl in slices
        )
        sections.append(
            f"""
<section>
  <h2>{geo_label}</h2>
  <table class="matrix">
    <thead><tr><th>Type</th>{slice_headers}</tr></thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</section>
"""
        )

    # Full directory listing (all dated suites)
    listing_rows = []
    for s in sorted(all_suites, key=lambda x: (x["geo"], x["focus"], x["slice"], x["day"]), reverse=True):
        status = "ready" if s.get("ready") else "missing index"
        href = s.get("href") or "#"
        link = (
            f'<a href="{href}">{s["name"]}</a>'
            if s.get("ready")
            else f'<span class="miss">{s["name"]}</span>'
        )
        listing_rows.append(
            f"<tr><td>{link}</td><td>{s['geo']}</td><td>{s['focus']}</td>"
            f"<td>{s['slice']}</td><td>{s['day']}</td><td>{status}</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>990tools report master index</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      margin: 1.5rem; color: #1a1a1a; line-height: 1.45; max-width: 1100px;
    }}
    h1 {{ margin-bottom: 0.25rem; }}
    .meta {{ color: #555; font-size: 0.9rem; margin-bottom: 1.25rem; }}
    section {{ margin: 1.75rem 0; }}
    h2 {{ font-size: 1.15rem; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.35rem; }}
    table.matrix {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-top: 0.75rem; }}
    table.matrix th, table.matrix td {{
      border: 1px solid #ddd; padding: 0.55rem 0.6rem; text-align: left; vertical-align: top;
    }}
    table.matrix thead th {{ background: #f4f4f4; }}
    table.matrix tbody th {{ background: #fafafa; width: 11rem; }}
    td.ok {{ background: #f0fdf4; }}
    td.pending {{ background: #fff7ed; color: #9a3412; }}
    td.miss {{ background: #f9fafb; color: #9ca3af; text-align: center; }}
    a {{ color: #0b57d0; text-decoration: none; font-weight: 600; }}
    a:hover {{ text-decoration: underline; }}
    .sub {{ font-size: 0.75rem; color: #6b7280; font-weight: 400; margin-top: 0.2rem; }}
    table.list {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    table.list th, table.list td {{ border: 1px solid #eee; padding: 0.35rem 0.5rem; }}
    table.list th {{ background: #f4f4f4; position: sticky; top: 0; }}
    footer {{ margin-top: 2rem; color: #666; font-size: 0.85rem; }}
    .legend span {{ display: inline-block; margin-right: 1rem; font-size: 0.85rem; }}
    .swatch {{ display: inline-block; width: 0.85rem; height: 0.85rem; border-radius: 2px; vertical-align: -1px; margin-right: 0.25rem; border: 1px solid #ddd; }}
    .swatch.ok {{ background: #f0fdf4; }}
    .swatch.pending {{ background: #fff7ed; }}
    .swatch.miss {{ background: #f9fafb; }}
  </style>
</head>
<body>
  <header>
    <h1>990tools cluster reports</h1>
    <p class="meta">Master index · generated {generated} · scanned <code>{reports_dir}</code></p>
    <p class="legend">
      <span><i class="swatch ok"></i> ready</span>
      <span><i class="swatch pending"></i> suite dir, no index yet</span>
      <span><i class="swatch miss"></i> not generated</span>
    </p>
  </header>

  <p class="meta">
    Location slices = colocator / zipcode / loose_colocator / address × focus types.
    Rank metrics: DOT = active PUs · FEC/$ grants = $ (grants exclude suppressed names) ·
    contractor = distinct addresses · medicare = provider rows.
  </p>

  {"".join(sections)}

  <section>
    <h2>All suite directories</h2>
    <table class="list">
      <thead>
        <tr><th>Directory</th><th>Geo</th><th>Focus</th><th>Slice</th><th>Day</th><th>Status</th></tr>
      </thead>
      <tbody>
        {"".join(listing_rows) if listing_rows else "<tr><td colspan=6>No suites found</td></tr>"}
      </tbody>
    </table>
  </section>

  <footer>
    <p>Open this file in a browser from the <code>reports/</code> folder (relative links).</p>
    <p>Rebuild: <code>python3 build_master_index.py</code></p>
  </footer>
</body>
</html>
"""


def main() -> int:
    p = argparse.ArgumentParser(description="Build reports/master_index.html")
    p.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: <reports-dir>/master_index.html)",
    )
    p.add_argument(
        "--all-days",
        action="store_true",
        help="Matrix uses every day (default: latest day per focus×slice)",
    )
    args = p.parse_args()
    reports_dir = args.reports_dir.resolve()
    out = args.out or (reports_dir / OUT_NAME)

    all_suites = collect_suites(reports_dir)
    matrix = all_suites if args.all_days else pick_latest(all_suites)
    html = render_html(matrix, all_suites=all_suites, reports_dir=reports_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    ready = sum(1 for s in matrix if s.get("ready"))
    print(f"Wrote {out} ({ready}/{len(matrix)} matrix cells ready, {len(all_suites)} suite dirs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
