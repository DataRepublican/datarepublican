#!/usr/bin/env python3
"""Build "Widen:" navigation links: address → colocator → loose → state."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from generate_address_reports import slugify_address  # type: ignore
from map_points import parse_ll, parse_zip5, zip_from_text  # type: ignore


def _round_half_away(n: float) -> float:
    """Match DuckDB ROUND half-away-from-zero for positive/negative."""
    if n >= 0:
        return math.floor(n + 0.5)
    return math.ceil(n - 0.5)


def tight_ll_to_loose_key(ll_key: str, step: float = 0.5) -> str | None:
    """LL:lat:lon → 0.5° grid key LL:rLat:rLon (same as generate_address_reports)."""
    parsed = parse_ll(ll_key)
    if not parsed:
        return None
    lat, lon = parsed
    rlat = _round_half_away(lat / step) * step
    rlon = _round_half_away(lon / step) * step
    return f"LL:{rlat:.1f}:{rlon:.1f}"


def suite_dirname(
    focus: str,
    slice_by: str,
    day: str | None = None,
    *,
    by_state: bool = False,
) -> str:
    """Stable public dirname. Date suffix only when ``day`` is set (legacy lookup)."""
    if by_state:
        f = "dot" if focus in ("", "dot", None) else focus
        base = f"{f}_{slice_by}_by_state"
    elif focus in ("", "dot", None):
        base = f"{slice_by}_clusters"
    else:
        base = f"{focus}_{slice_by}_clusters"
    if day:
        return f"{base}_{day}"
    return base


def detail_filename(slice_by: str, cluster_key: str, *, state: str | None = None) -> str:
    if state:
        return f"{slugify_address(f'{state}-{slice_by}-{cluster_key}')}.html"
    return f"{slugify_address(f'{slice_by}-{cluster_key}')}.html"


def fetch_effective_colocator(conn, canonical_address: str) -> str | None:
    """Best colocator for a street address (Addresses + Geocoding)."""
    try:
        # Geocoding is keyed by canonical_address (no address_id FK).
        row = conn.execute(
            """
            SELECT COALESCE(
                NULLIF(TRIM(a.colocator), ''),
                NULLIF(TRIM(g.colocator), ''),
                CASE
                    WHEN g.latitude IS NOT NULL AND g.longitude IS NOT NULL
                    THEN 'LL:' || CAST(g.latitude AS VARCHAR) || ':'
                         || CAST(g.longitude AS VARCHAR)
                END,
                CASE
                    WHEN a.latitude IS NOT NULL AND a.longitude IS NOT NULL
                    THEN 'LL:' || CAST(a.latitude AS VARCHAR) || ':'
                         || CAST(a.longitude AS VARCHAR)
                END
            )
            FROM Addresses a
            LEFT JOIN Geocoding g
              ON g.canonical_address = a.canonical_address
            WHERE a.canonical_address = ?
            LIMIT 1
            """,
            [canonical_address],
        ).fetchone()
        if row and row[0] and str(row[0]).strip():
            return str(row[0]).strip()
    except Exception:
        # Fallback: Addresses only
        try:
            row = conn.execute(
                """
                SELECT COALESCE(
                    NULLIF(TRIM(colocator), ''),
                    CASE
                        WHEN latitude IS NOT NULL AND longitude IS NOT NULL
                        THEN 'LL:' || CAST(latitude AS VARCHAR) || ':'
                             || CAST(longitude AS VARCHAR)
                    END
                )
                FROM Addresses
                WHERE canonical_address = ?
                LIMIT 1
                """,
                [canonical_address],
            ).fetchone()
            if row and row[0] and str(row[0]).strip():
                return str(row[0]).strip()
        except Exception:
            pass
    return None


def fetch_primary_state(
    conn,
    slice_by: str,
    cluster_key: str,
    *,
    lat_long: bool = False,
) -> str | None:
    """Most common Addresses.state for members of this cluster key."""
    from generate_address_reports import _member_filter_sql  # type: ignore

    try:
        key_expr, where, gjoin = _member_filter_sql(
            slice_by, conn, lat_long=lat_long
        )
        row = conn.execute(
            f"""
            SELECT UPPER(TRIM(a.state)) AS st, COUNT(*) AS c
            FROM Addresses a
            {gjoin}
            WHERE ({key_expr}) = ?
              AND ({where})
              AND a.state IS NOT NULL AND LENGTH(TRIM(a.state)) = 2
            GROUP BY 1
            ORDER BY c DESC
            LIMIT 1
            """,
            [cluster_key],
        ).fetchone()
        if row and row[0]:
            return str(row[0]).upper()
    except Exception:
        pass
    return None


def os_path_rel(from_dir: Path, to_path: Path) -> str:
    import os

    return os.path.relpath(str(to_path), str(from_dir))


def _detail_path(
    *,
    reports_dir: Path,
    focus: str,
    target_slice: str,
    target_key: str,
    report_day: str | None,
    by_state: bool = False,
    state_code: str | None = None,
) -> Path:
    if by_state and state_code:
        suite = suite_dirname(focus, target_slice, report_day, by_state=True)
        if target_key == "__STATE_INDEX__":
            return reports_dir / suite / "states" / state_code / "index.html"
        fn = detail_filename(target_slice, target_key, state=state_code)
        return reports_dir / suite / "states" / state_code / fn
    suite = suite_dirname(focus, target_slice, report_day, by_state=False)
    fn = detail_filename(target_slice, target_key)
    return reports_dir / suite / fn


def _find_existing_detail(
    *,
    reports_dir: Path,
    focus: str,
    target_slice: str,
    target_key: str,
    report_day: str | None,
    state_code: str | None = None,
) -> tuple[Path, str] | None:
    """Prefer undated national, then undated by-state, then dated leftovers.

    National suites only keep top-N clusters, so address → colocator often needs
    the by-state detail page (fuller coverage for that state).
    """
    candidates: list[tuple[Path, str]] = []
    # Stable undated first — dated globs like colocator_clusters_* miss these.
    for day in (None, report_day or None):
        candidates.append(
            (
                _detail_path(
                    reports_dir=reports_dir,
                    focus=focus,
                    target_slice=target_slice,
                    target_key=target_key,
                    report_day=day,
                ),
                "national",
            )
        )
        if state_code:
            candidates.append(
                (
                    _detail_path(
                        reports_dir=reports_dir,
                        focus=focus,
                        target_slice=target_slice,
                        target_key=target_key,
                        report_day=day,
                        by_state=True,
                        state_code=state_code,
                    ),
                    "by_state",
                )
            )
    seen: set[Path] = set()
    for path, kind in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            return path, kind

    # Dated leftovers only (colocator_clusters_YYYY-MM-DD). Undated already tried.
    fn_nat = detail_filename(target_slice, target_key)
    if focus in ("", "dot", None):
        nat_glob = f"{target_slice}_clusters_*/{fn_nat}"
        st_glob = (
            f"dot_{target_slice}_by_state_*/states/{state_code}/"
            f"{detail_filename(target_slice, target_key, state=state_code)}"
            if state_code
            else None
        )
    else:
        nat_glob = f"{focus}_{target_slice}_clusters_*/{fn_nat}"
        st_glob = (
            f"{focus}_{target_slice}_by_state_*/states/{state_code}/"
            f"{detail_filename(target_slice, target_key, state=state_code)}"
            if state_code
            else None
        )
    for pattern in (nat_glob, st_glob):
        if not pattern:
            continue
        hits = sorted(reports_dir.glob(pattern), reverse=True)
        if hits:
            kind = "by_state" if "_by_state_" in str(hits[0]) else "national"
            return hits[0], kind
    return None


def build_widen_links(
    *,
    focus: str,
    slice_by: str,
    cluster_key: str,
    sample_address: str | None = None,
    state: str | None = None,
    report_day: str | None,
    reports_dir: Path,
    output_dir: Path,
    conn=None,
    lat_long: bool = False,
    context: str = "national",  # national | by_state
) -> list[dict[str, str]]:
    """Return [{label, href, key, level}, ...] for Widen: UI."""
    focus = focus or "dot"
    links: list[dict[str, str]] = []
    key = str(cluster_key or "").strip()
    sample = sample_address or ""
    st = (state or "").upper() or None

    # Resolve colocator for address (or zip via sample)
    colocator_key: str | None = None
    if slice_by == "address" and conn is not None:
        colocator_key = fetch_effective_colocator(conn, key)
    elif slice_by == "colocator":
        colocator_key = key
    elif slice_by == "zipcode" and conn is not None and sample:
        # optional: colocator of sample street — skip if multi-homed
        colocator_key = fetch_effective_colocator(conn, sample)

    # Loose key from tight LL (or already loose)
    loose_key: str | None = None
    if slice_by == "loose_colocator":
        loose_key = key if parse_ll(key) else None
    elif colocator_key and parse_ll(colocator_key):
        loose_key = tight_ll_to_loose_key(colocator_key)
    elif parse_ll(key):
        loose_key = tight_ll_to_loose_key(key)

    # State
    if not st and conn is not None:
        st = fetch_primary_state(conn, slice_by, key, lat_long=lat_long)
    if not st and sample:
        # crude: last , XX, zip pattern
        m = re.search(r",\s*([A-Za-z]{2})\s*,\s*\d{5}", sample)
        if m:
            st = m.group(1).upper()
    if not st and key:
        m = re.search(r",\s*([A-Za-z]{2})\s*,\s*\d{5}", key)
        if m:
            st = m.group(1).upper()

    def add(
        level: str,
        label: str,
        target_slice: str,
        target_key: str,
        *,
        by_state: bool = False,
        state_code: str | None = None,
        prefer_existing: bool = False,
    ):
        sc = state_code or st
        target: Path | None = None
        exists = "0"
        resolved_kind = "national" if not by_state else "by_state"

        if prefer_existing or target_key == "__STATE_INDEX__":
            found = _find_existing_detail(
                reports_dir=reports_dir,
                focus=focus,
                target_slice=target_slice,
                target_key=target_key,
                report_day=report_day,
                state_code=sc,
            )
            if found:
                target, resolved_kind = found
                exists = "1"
            elif sc and target_key != "__STATE_INDEX__":
                st_idx = (
                    reports_dir
                    / suite_dirname(focus, target_slice, None, by_state=True)
                    / "states"
                    / sc
                    / "index.html"
                )
                if st_idx.exists():
                    target, resolved_kind, exists = st_idx, "by_state_index", "1"
                    label = f"{label} · {sc} index"
            if target is None and target_key != "__STATE_INDEX__":
                nat_idx = (
                    reports_dir
                    / suite_dirname(focus, target_slice, None, by_state=False)
                    / "index.html"
                )
                if nat_idx.exists():
                    target, resolved_kind, exists = nat_idx, "national_index", "1"
                    label = f"{label} · suite"

        if target is None:
            target = _detail_path(
                reports_dir=reports_dir,
                focus=focus,
                target_slice=target_slice,
                target_key=target_key,
                report_day=None,
                by_state=by_state,
                state_code=sc if by_state else state_code,
            )
            exists = "1" if target.exists() else "0"
            if by_state:
                resolved_kind = "by_state"

        if resolved_kind == "by_state" and "state" not in label.lower():
            label = f"{label} · state pack"

        href = os_path_rel(output_dir, target)
        links.append(
            {
                "level": level,
                "label": label,
                "href": href,
                "key": target_key if target_key != "__STATE_INDEX__" else sc or "",
                "exists": exists,
                "scope": resolved_kind,
            }
        )

    zip5 = parse_zip5(key) or zip_from_text(sample) or zip_from_text(key)

    # address → colocator → loose → zip (same focus). National top-N often
    # omits the key; fall back to by-state detail, then that slice's index.
    if slice_by == "address" and colocator_key:
        add(
            "colocator",
            "Colocator (all address variants)",
            "colocator",
            colocator_key,
            prefer_existing=True,
            state_code=st,
        )

    if slice_by in ("address", "colocator") and loose_key:
        add(
            "loose_colocator",
            "Loose colocator (0.5° cell)",
            "loose_colocator",
            loose_key,
            prefer_existing=True,
            state_code=st,
        )

    if (
        slice_by in ("address", "colocator", "loose_colocator")
        and zip5
    ):
        add(
            "zipcode",
            f"ZIP {zip5}",
            "zipcode",
            zip5,
            prefer_existing=True,
            state_code=st,
        )

    # 3) Zip / address / colocator / loose → state index
    if st and slice_by in (
        "address",
        "colocator",
        "loose_colocator",
        "zipcode",
    ):
        # If we're already on a by-state page for this state, link to state index only
        if context == "by_state":
            add(
                "state",
                f"State {st} (all clusters)",
                slice_by,
                "__STATE_INDEX__",
                by_state=True,
                state_code=st,
                prefer_existing=True,
            )
        else:
            # National → by-state suite for same focus + current slice's "widest" geo
            # Prefer loose if we have it, else zip, else colocator, else address
            state_slice = (
                "loose_colocator"
                if loose_key
                else ("zipcode" if slice_by == "zipcode" or parse_zip5(key) or zip_from_text(sample) else slice_by)
            )
            # For address/colocator national, jump to state index on loose or colocator by-state
            if slice_by in ("address", "colocator") and loose_key:
                state_slice = "loose_colocator"
            elif slice_by == "zipcode":
                state_slice = "zipcode"
            elif slice_by == "loose_colocator":
                state_slice = "loose_colocator"
            else:
                state_slice = "colocator"
            add(
                "state",
                f"State {st}",
                state_slice,
                "__STATE_INDEX__",
                by_state=True,
                state_code=st,
                prefer_existing=True,
            )

    return links


_WIDEN_SECTION_RE = re.compile(
    r'<section class="widen-nav"[^>]*>.*?</section>',
    re.DOTALL | re.IGNORECASE,
)

_SUITE_DIR_RE = re.compile(
    r"^(?:(?P<focus>grants_out|fec_committee|medicare|contractor|grants|usg|dot)_)?"
    r"(?P<slice>address|colocator|zipcode|loose_colocator)_"
    r"(?P<level>clusters|by_state)$"
)


def _key_from_html(text: str, slice_by: str) -> tuple[str | None, str | None]:
    """Recover cluster_key + sample from the detail <h1> when JSON is missing."""
    import html as html_lib

    m = re.search(r"<h1\b[^>]*>(.*?)</h1>", text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None, None
    inner = re.sub(r"<[^>]+>", "", m.group(1))
    inner = html_lib.unescape(inner)
    inner = re.sub(r"\s+", " ", inner).strip()
    if not inner:
        return None, None
    if re.search(r"·\s*e\.g\.\s*", inner, re.I):
        key, sample = re.split(r"·\s*e\.g\.\s*", inner, maxsplit=1)
        key, sample = key.strip(), sample.strip()
    else:
        key, sample = inner, inner
    if slice_by == "zipcode":
        z = parse_zip5(key) or zip_from_text(inner)
        return (z or key), sample
    return key, sample


def render_widen_nav_html(links: list[dict[str, str]]) -> str:
    if not links:
        return ""
    parts = [
        '<section class="widen-nav" aria-label="Widen geographic scope">',
        '  <strong class="widen-label">Widen:</strong>',
        '  <span class="widen-links">',
    ]
    for i, w in enumerate(links):
        if i:
            parts.append('    <span class="widen-sep">·</span>')
        missing = w.get("exists") == "0"
        title = w.get("key") or ""
        if missing:
            title = f"{title} — page not generated".strip(" —")
        elif w.get("scope") == "by_state":
            title = f"{title} · by-state pack".strip()
        cls = "widen-link missing" if missing else "widen-link"
        href = w.get("href") or "#"
        label = w.get("label") or ""
        parts.append(
            f'  <a href="{href}" class="{cls}" title="{title}">{label}</a>'
        )
    parts.extend(["  </span>", "</section>"])
    return "\n".join(parts)


def refresh_widen_in_reports(
    reports_dir: Path,
    conn,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Rebuild Widen: nav on existing cluster HTML (no full suite regen)."""
    import json as json_lib

    stats = {"pages": 0, "updated": 0, "skipped": 0}
    for suite in sorted(p for p in reports_dir.iterdir() if p.is_dir()):
        parsed = _SUITE_DIR_RE.match(suite.name)
        if not parsed:
            continue
        focus = parsed.group("focus") or "dot"
        slice_by = parsed.group("slice")
        level = parsed.group("level")
        htmls = (
            list((suite / "states").rglob("*.html"))
            if level == "by_state"
            else list(suite.glob("*.html"))
        )
        for html_path in htmls:
            if html_path.name == "index.html":
                continue
            stats["pages"] += 1
            sidecar = html_path.parent / "data" / f"{html_path.stem}.json"
            cluster_key = None
            sample = None
            state = None
            text = html_path.read_text(encoding="utf-8", errors="replace")
            if sidecar.is_file():
                try:
                    meta = json_lib.loads(sidecar.read_text(encoding="utf-8"))
                    cluster_key = str(meta.get("cluster_key") or "").strip()
                    sample = meta.get("sample_address") or meta.get("canonical_address")
                    state = meta.get("state")
                except Exception:
                    meta = {}
            if not cluster_key:
                cluster_key, sample = _key_from_html(text, slice_by)
            if not cluster_key:
                stats["skipped"] += 1
                continue
            st_code = None
            if level == "by_state":
                # .../states/PA/foo.html
                try:
                    st_code = html_path.parent.name
                    if len(st_code) != 2:
                        st_code = state
                except Exception:
                    st_code = state
            links = build_widen_links(
                focus=focus,
                slice_by=slice_by,
                cluster_key=cluster_key,
                sample_address=sample,
                state=st_code or state,
                report_day=None,
                reports_dir=reports_dir,
                output_dir=html_path.parent,
                conn=conn,
                context="by_state" if level == "by_state" else "national",
            )
            nav = render_widen_nav_html(links)
            if _WIDEN_SECTION_RE.search(text):
                new_text = _WIDEN_SECTION_RE.sub(nav, text, count=1)
            elif nav:
                # Insert after </header>
                new_text = re.sub(
                    r"</header>",
                    "</header>\n  " + nav + "\n",
                    text,
                    count=1,
                    flags=re.IGNORECASE,
                )
            else:
                stats["skipped"] += 1
                continue
            if new_text == text:
                stats["skipped"] += 1
                continue
            if not dry_run:
                html_path.write_text(new_text, encoding="utf-8")
            stats["updated"] += 1
            if stats["updated"] % 500 == 0:
                print(f"  updated {stats['updated']} ({suite.name})", flush=True)
    return stats


if __name__ == "__main__":
    import argparse
    import os

    import duckdb

    ap = argparse.ArgumentParser(description="Rebuild Widen: links on existing reports")
    ap.add_argument(
        "--reports-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "reports",
    )
    ap.add_argument("--db-path", default=os.environ.get("IRS990_DB_PATH", "/Volumes/Data/final/irs990.duckdb"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    reports = args.reports_dir.expanduser().resolve()
    conn = duckdb.connect(args.db_path, read_only=True)
    try:
        s = refresh_widen_in_reports(reports, conn, dry_run=args.dry_run)
        print(f"Done pages={s['pages']} updated={s['updated']} skipped={s['skipped']}")
    finally:
        conn.close()
