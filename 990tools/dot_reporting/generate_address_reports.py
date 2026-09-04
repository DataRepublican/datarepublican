#!/usr/bin/env python3
"""
generate_address_reports.py — Static HTML cluster reports for fraud precursor review.

Slice modes group Addresses by different keys (same drill-down / DOT tooling):
  address          — canonical_address (default, original behavior)
  colocator        — tight colocator (LL:/PO:/FA:…)
  zipcode          — Addresses.zip_code equality (valid US zips via JOIN Zips)
  loose_colocator  — 0.5° grid (column if set, else derived from lat/lon)

For non-address slices, each detail page also breaks the cluster into
distinct canonical_address subgroups (suite/building splits) and groups
DOT carriers by street address.

DOT matching is **physical only** (`dot_carrier_phy`). Mailing
(`dot_carrier_mail`) is not counted for stacks — see dot_policy.py.

Spec: address_cluster_report.md

Usage:
  python generate_address_reports.py
  python generate_address_reports.py --db-path /Volumes/Data/final/irs990.duckdb.geolocate
  python generate_address_reports.py --slice-by colocator --min-dot-carriers 50
  python generate_address_reports.py --slice-by colocator --lat-long   # LL: only (no PO boxes)
  python generate_address_reports.py --slice-by zipcode --max-clusters 50
  python generate_address_reports.py --slice-by loose_colocator --min-multi-type 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import duckdb
from mako.template import Template

DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb.geolocate"
DEFAULT_FINAL_DIR = "/Volumes/Data/final"
SCRIPT_DIR = Path(__file__).resolve().parent

# How clusters are defined. SQL expressions are relative to Addresses alias `a` where needed.
SLICE_MODES: dict[str, dict[str, str]] = {
    "address": {
        "label": "canonical address",
        "key_expr": "canonical_address",
        "where": "canonical_address IS NOT NULL AND TRIM(canonical_address) != ''",
        "out_dir_prefix": "address_clusters",
    },
    "colocator": {
        "label": "colocator",
        "key_expr": "colocator",
        "where": "colocator IS NOT NULL AND TRIM(colocator) != ''",
        "out_dir_prefix": "colocator_clusters",
    },
    "zipcode": {
        "label": "zip code",
        # Bare column — upstream split_zip_code already stores ZIP5 (+ zip4 separate).
        # resolve_slice_mode() upgrades to INNER JOIN Zips (valid US catalog) when present.
        "key_expr": "zip_code",
        "where": "zip_code IS NOT NULL AND zip_code != ''",
        "out_dir_prefix": "zipcode_clusters",
    },
    "loose_colocator": {
        "label": "loose colocator (0.5°)",
        # Derived from lat/lon when loose_colocator column is absent (older snapshots).
        # Runtime may upgrade key_expr to prefer stored column — see resolve_slice_mode().
        "key_expr": (
            "CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL "
            "THEN 'LL:' || CAST(ROUND(latitude / 0.5) * 0.5 AS VARCHAR) "
            "|| ':' || CAST(ROUND(longitude / 0.5) * 0.5 AS VARCHAR) "
            "ELSE NULL END"
        ),
        "where": "latitude IS NOT NULL AND longitude IS NOT NULL",
        "out_dir_prefix": "loose_colocator_clusters",
    },
}

CSS = """
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, sans-serif; margin: 1.5rem; color: #1a1a1a; line-height: 1.45; max-width: 1200px; }
header h1 { margin-bottom: 0.25rem; }
.meta { color: #555; font-size: 0.9rem; }
nav { margin-bottom: 1rem; }
nav.breadcrumbs { margin: 0 0 1rem; font-size: 0.88rem; color: #555; line-height: 1.5; }
nav.breadcrumbs a { color: #0b57d0; text-decoration: none; font-weight: 500; }
nav.breadcrumbs a:hover { text-decoration: underline; }
nav.breadcrumbs .bc-sep { margin: 0 0.35rem; color: #9ca3af; }
nav.breadcrumbs .bc-current { color: #111; font-weight: 600; }
.rank-dot {
  display: inline-block; width: 0.7rem; height: 0.7rem; border-radius: 999px;
  border: 1px solid rgba(0,0,0,0.12); vertical-align: middle; margin-right: 0.35rem;
}
.rank-dot.high { background: #b91c1c; }
.rank-dot.mid { background: #d97706; }
.rank-dot.low { background: #2563eb; }
.rank-dot.top { background: #7f1d1d; box-shadow: 0 0 0 1px #fecaca; } /* ≥p99 within list */
.rank-dot.po { background: #a78bfa; border-color: #7c3aed; }
.rank-dot.none { background: #e5e7eb; }
.widen-nav {
  margin: 0.5rem 0 1rem; padding: 0.55rem 0.75rem;
  background: #f0f7ff; border: 1px solid #cfe2ff; border-radius: 8px;
  font-size: 0.9rem;
}
.widen-nav .widen-label { color: #174ea6; margin-right: 0.5rem; }
.widen-nav a.widen-link { color: #0b57d0; font-weight: 600; text-decoration: none; }
.widen-nav a.widen-link:hover { text-decoration: underline; }
.widen-nav a.widen-link.missing { opacity: 0.65; font-weight: 500; }
.widen-nav .widen-sep { color: #94a3b8; margin: 0 0.35rem; }

table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.88rem; }
th, td { border: 1px solid #ddd; padding: 0.45rem 0.55rem; text-align: left; vertical-align: top; }
th { background: #f4f4f4; position: sticky; top: 0; }
tr:nth-child(even) { background: #fafafa; }
a { color: #0b57d0; }
.dot-heavy { background: #fff4e5 !important; }
.flag-misrep { background: #fde8e8; }
.flag-grift { background: #fff0d6; }
.chips { margin: 0.75rem 0; }
.chip { display: inline-block; background: #e8f0fe; color: #174ea6; padding: 0.2rem 0.55rem; border-radius: 999px; font-size: 0.8rem; margin-right: 0.35rem; }
.physical { background: #f0f7ff; border-left: 4px solid #0b57d0; padding: 0.75rem 1rem; margin: 1rem 0; }
.cards { display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 1rem 0; }
.card { background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 8px; padding: 0.75rem 1rem; min-width: 110px; }
.card strong { display: block; font-size: 1.35rem; }
.card span { font-size: 0.8rem; color: #666; }
.types { font-size: 0.9rem; }
footer { margin-top: 2rem; color: #666; font-size: 0.85rem; }
@media (max-width: 700px) { body { margin: 0.75rem; } table { font-size: 0.8rem; } }
"""


def _addresses_has_column(conn: duckdb.DuckDBPyConnection, col: str) -> bool:
    try:
        cols = {r[0] for r in conn.execute("DESCRIBE Addresses").fetchall()}
        return col in cols
    except Exception:
        return False


def _table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    try:
        tables = {str(r[0]) for r in conn.execute("SHOW TABLES").fetchall()}
        return name in tables or name.lower() in {t.lower() for t in tables}
    except Exception:
        return False


def mode_uses_alias(mode: dict[str, str]) -> bool:
    """True when from_sql aliases Addresses as `a` (colocator Geocoding join or Zips join)."""
    return mode.get("needs_geocoding_join") == "1" or mode.get("uses_alias") == "1"


# Effective colocator: Addresses rarely stores LL: — most live on Geocoding after geocode.
_COLOCATOR_KEY_EXPR = (
    "COALESCE(NULLIF(TRIM(a.colocator), ''), NULLIF(TRIM(g.colocator), ''))"
)
_COLOCATOR_LL_KEY_EXPR = (
    "COALESCE("
    "CASE WHEN a.colocator LIKE 'LL:%' THEN a.colocator END, "
    "CASE WHEN g.colocator LIKE 'LL:%' THEN g.colocator END, "
    "CASE WHEN g.latitude IS NOT NULL AND g.longitude IS NOT NULL "
    "THEN 'LL:' || CAST(g.latitude AS VARCHAR) || ':' || CAST(g.longitude AS VARCHAR) END, "
    "CASE WHEN a.latitude IS NOT NULL AND a.longitude IS NOT NULL "
    "THEN 'LL:' || CAST(a.latitude AS VARCHAR) || ':' || CAST(a.longitude AS VARCHAR) END"
    ")"
)
_COLOCATOR_FROM = (
    "FROM Addresses a "
    "LEFT JOIN Geocoding g ON g.geocoding_id = a.geocoding_id"
)
# Valid US ZIP catalog (PK on Zips.zip). Equality join is sargable; no REGEXP.
_ZIP_FROM = (
    "FROM Addresses a "
    "INNER JOIN Zips z ON z.zip = a.zip_code"
)


def resolve_slice_mode(
    slice_by: str,
    conn: duckdb.DuckDBPyConnection | None = None,
    *,
    lat_long: bool = False,
) -> dict[str, str]:
    """Copy of SLICE_MODES entry; upgrades colocator/loose/zip for real production shape.

    colocator keys resolve via Addresses LEFT JOIN Geocoding (Addresses.colocator is
    often empty for LL: while Geocoding holds the LL: string / lat-lon).

    zipcode uses bare Addresses.zip_code (already ZIP5 from split_zip_code). When the
    Zips catalog table is present, INNER JOIN Zips filters to valid US zips and keeps
    predicates sargable (a.zip_code = ? / z.zip = a.zip_code). Never REGEXP_REPLACE.

    lat_long: with --slice-by colocator, keep only LL:lat:lon keys (drop PO:/FA:/…).
    """
    mode = dict(SLICE_MODES[slice_by])
    mode.setdefault("from_sql", "FROM Addresses")
    mode.setdefault("needs_geocoding_join", "0")
    mode.setdefault("uses_alias", "0")
    mode.setdefault("member_join_extra", "")

    if slice_by == "loose_colocator" and conn is not None and _addresses_has_column(conn, "loose_colocator"):
        mode["key_expr"] = (
            "COALESCE("
            "NULLIF(TRIM(loose_colocator), ''), "
            "CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL "
            "THEN 'LL:' || CAST(ROUND(latitude / 0.5) * 0.5 AS VARCHAR) "
            "|| ':' || CAST(ROUND(longitude / 0.5) * 0.5 AS VARCHAR) "
            "ELSE NULL END)"
        )
        mode["where"] = (
            "(loose_colocator IS NOT NULL AND TRIM(loose_colocator) != '') "
            "OR (latitude IS NOT NULL AND longitude IS NOT NULL)"
        )

    if slice_by == "zipcode":
        if conn is not None and _table_exists(conn, "Zips"):
            # Catalog-validated, index-friendly equality — no report-time normalization.
            mode["key_expr"] = "a.zip_code"
            mode["where"] = "a.zip_code IS NOT NULL AND a.zip_code != ''"
            mode["from_sql"] = _ZIP_FROM
            mode["uses_alias"] = "1"
            # Member fetches: equality on zip_code is enough (keys only come from Zips).
            mode["member_join_extra"] = ""
            mode["label"] = "zip code (zip_code ∈ Zips)"
        else:
            mode["key_expr"] = "zip_code"
            mode["where"] = "zip_code IS NOT NULL AND zip_code != ''"
            mode["label"] = "zip code (Addresses.zip_code)"

    if slice_by == "colocator":
        mode["needs_geocoding_join"] = "1"
        mode["from_sql"] = _COLOCATOR_FROM
        if lat_long:
            mode["key_expr"] = _COLOCATOR_LL_KEY_EXPR
            mode["where"] = (
                "(a.colocator LIKE 'LL:%' OR g.colocator LIKE 'LL:%' "
                "OR (g.latitude IS NOT NULL AND g.longitude IS NOT NULL) "
                "OR (a.latitude IS NOT NULL AND a.longitude IS NOT NULL))"
            )
            mode["label"] = "colocator (LL: only, via Geocoding)"
            mode["out_dir_prefix"] = "colocator_ll_clusters"
        else:
            mode["key_expr"] = _COLOCATOR_KEY_EXPR
            mode["where"] = (
                f"({_COLOCATOR_KEY_EXPR}) IS NOT NULL "
                f"AND TRIM(CAST(({_COLOCATOR_KEY_EXPR}) AS VARCHAR)) != ''"
            )
            mode["label"] = "colocator (Addresses + Geocoding)"
    elif lat_long:
        raise ValueError("--lat-long only applies with --slice-by colocator")

    return mode


def build_cluster_sql(
    slice_by: str,
    conn: duckdb.DuckDBPyConnection | None = None,
    *,
    lat_long: bool = False,
) -> str:
    mode = resolve_slice_mode(slice_by, conn, lat_long=lat_long)
    key = mode["key_expr"]
    where = mode["where"]
    from_sql = mode.get("from_sql", "FROM Addresses")
    # Aliased modes (Geocoding / Zips): key/where already use a./g./z. prefixes.
    # Plain Address modes use bare column names on unaliased Addresses.
    if mode_uses_alias(mode):
        canon = "a.canonical_address"
        atype = "a.address_type"
        owner = "a.owner_id"
        aid = "a.address_id"
        zipc = "a.zip_code"
        lat = "a.latitude"
        lon = "a.longitude"
        colo = "a.colocator"
    else:
        canon = "canonical_address"
        atype = "address_type"
        owner = "owner_id"
        aid = "address_id"
        zipc = "zip_code"
        lat = "latitude"
        lon = "longitude"
        colo = "colocator"

    return f"""
WITH keyed AS (
    SELECT
        ({key}) AS cluster_key,
        {canon} AS canonical_address,
        {atype} AS address_type,
        {owner} AS owner_id,
        {aid} AS address_id,
        {zipc} AS zip_code,
        {lat} AS latitude,
        {lon} AS longitude,
        {colo} AS colocator
    {from_sql}
    WHERE {where}
      AND ({key}) IS NOT NULL
      AND TRIM(CAST(({key}) AS VARCHAR)) != ''
),
base AS (
    SELECT
        cluster_key,
        COUNT(*) AS total_rows,
        COUNT(DISTINCT address_type) AS multi_type_count,
        LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
        SUM(CASE WHEN address_type = 'dot_carrier_phy' THEN 1 ELSE 0 END)::BIGINT AS dot_carrier_count,
        SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_count,
        SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_count,
        SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_count,
        -- Representative street address for maps / notes (any non-empty canonical in cluster)
        ANY_VALUE(CASE
            WHEN canonical_address IS NOT NULL AND TRIM(canonical_address) != ''
            THEN canonical_address END) AS sample_address,
        -- Structured geo from Addresses (maps must not re-parse street text)
        ANY_VALUE(NULLIF(TRIM(zip_code), '')) AS zip_code,
        ANY_VALUE(latitude) AS latitude,
        ANY_VALUE(longitude) AS longitude,
        ANY_VALUE(NULLIF(TRIM(colocator), '')) AS colocator
    FROM keyed
    GROUP BY cluster_key
),
charity_signals AS (
    SELECT
        k.cluster_key,
        MAX(c.grift_ratio) AS max_grift_ratio,
        SUM(CASE
            WHEN UPPER(CAST(c.domestic_misrep_flag AS VARCHAR)) IN ('TRUE', '1', 'Y', 'YES', 'T')
            THEN 1 ELSE 0
        END)::BIGINT AS misrep_count
    FROM keyed k
    INNER JOIN Charities c ON c.charity_id = k.owner_id AND k.address_type = 'charity'
    GROUP BY k.cluster_key
),
dot_active AS (
    SELECT
        k.cluster_key,
        SUM(CASE WHEN d.status_code = 'A' THEN COALESCE(d.power_units, 0) ELSE 0 END)::BIGINT AS active_power_units
    FROM keyed k
    INNER JOIN dot_carriers d ON d.id = k.owner_id
        AND k.address_type = 'dot_carrier_phy'
    GROUP BY k.cluster_key
)
SELECT
    b.cluster_key,
    b.sample_address,
    b.total_rows,
    b.multi_type_count,
    b.address_types,
    b.dot_carrier_count,
    b.charity_count,
    b.grant_count,
    b.officer_count,
    cs.max_grift_ratio,
    COALESCE(cs.misrep_count, 0) AS misrep_count,
    COALESCE(da.active_power_units, 0) AS active_power_units,
    b.zip_code,
    b.latitude,
    b.longitude,
    b.colocator
FROM base b
LEFT JOIN charity_signals cs ON cs.cluster_key = b.cluster_key
LEFT JOIN dot_active da ON da.cluster_key = b.cluster_key
WHERE
    -- Phy carriers only; rank (DOT records, then address types) + LIMIT select the suite.
    -- Optional legacy floors (0 = off). Active PUs stay a display column.
    b.dot_carrier_count > 0
    AND (? <= 0 OR b.multi_type_count >= ?)
    AND (? <= 0 OR b.dot_carrier_count >= ?)
    AND (
        ? = 0
        OR COALESCE(cs.max_grift_ratio, 0) > 5
        OR COALESCE(cs.misrep_count, 0) > 0
    )
ORDER BY b.dot_carrier_count DESC, b.multi_type_count DESC, b.total_rows DESC
LIMIT ?
"""


def is_po_box(address: str) -> bool:
    """Detect if an address is a PO Box (for physical address red flagging)."""
    if not address:
        return False
    a = address.upper()
    return bool(re.search(r'\bP\.?\s*O\.?\s*BOX\b|\bPO\s*BOX\b|\bP\.?O\.?B\.?\b', a))


def slugify_address(addr: str) -> str:
    s = addr.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return (s.strip("-") or "cluster")[:120]


def google_maps_url(address: str, zoom: int = 17) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(address)}&zoom={zoom}"


def street_view_url(address: str, heading: int) -> str:
    """Generate Google Street View link with specific heading.
    0 = North, 90 = East, 180 = South, 270 = West.
    """
    return (
        "https://www.google.com/maps/@?api=1&map_action=pano"
        f"&viewpoint={quote_plus(address)}&heading={heading}&pitch=0"
    )


def fmt_money(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.2f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    if abs(value) >= 1_000:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def load_physical_notes(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k.strip(): v for k, v in data.items()}


def physical_note_for(canonical: str, notes: dict[str, str]) -> str | None:
    if not canonical:
        return None
    if canonical in notes:
        return notes[canonical]
    key_lower = canonical.lower()
    for k, v in notes.items():
        if k.lower() == key_lower:
            return v
    return None


def reason_codes(cluster: dict[str, Any], min_multi: int, min_dot: int) -> list[str]:
    codes = []
    if cluster["multi_type_count"] >= min_multi:
        codes.append("multi_type")
    if cluster["dot_carrier_count"] >= min_dot:
        codes.append("dot_stack")
    if (cluster.get("max_grift_ratio") or 0) > 5:
        codes.append("high_grift")
    if cluster.get("misrep_count", 0) > 0:
        codes.append("domestic_misrep")
    if cluster.get("phy_is_po_box"):
        codes.append("phy_po_box")
    return codes or ["threshold"]


def suspicion_score(cluster: dict) -> int:
    dot_count = cluster.get('dot_carrier_count', 0)
    active_count = cluster.get('dot_active_count', 0)
    inactive_count = cluster.get('dot_inactive_count', 0)
    active_power = cluster.get('dot_active_power_units', 0)
    inactive_power = cluster.get('dot_inactive_power_units', 0)
    multi_type = cluster.get('multi_type_count', 0)
    phy_is_po_box = cluster.get('phy_is_po_box', False)

    if dot_count == 0:
        return 0

    ia_ratio = inactive_count / dot_count if dot_count > 0 else 0

    score = 0
    score += dot_count * 1.2
    score += ia_ratio * 1400
    score += inactive_power * 1.6
    if ia_ratio > 0.5:
        score += active_power * 0.5
    else:
        score += active_power * 0.9
    if multi_type <= 2:
        score += 300
    if phy_is_po_box:
        score += 400
    return int(score)


def fetch_clusters(
    conn: duckdb.DuckDBPyConnection,
    slice_by: str,
    min_multi: int,
    min_dot: int,
    require_grift: bool,
    limit: int,
    *,
    lat_long: bool = False,
) -> list[dict[str, Any]]:
    sql = build_cluster_sql(slice_by, conn, lat_long=lat_long)
    rows = conn.execute(
        sql,
        [
            int(min_multi or 0),
            int(min_multi or 0),
            int(min_dot or 0),
            int(min_dot or 0),
            1 if require_grift else 0,
            limit,
        ],
    ).fetchall()
    cols = [
        "cluster_key", "sample_address", "total_rows", "multi_type_count", "address_types",
        "dot_carrier_count", "charity_count", "grant_count", "officer_count",
        "max_grift_ratio", "misrep_count", "active_power_units",
        "zip_code", "latitude", "longitude", "colocator",
    ]
    clusters = []
    for row in rows:
        c = dict(zip(cols, row))
        if isinstance(c["address_types"], str):
            c["address_types"] = [t.strip() for t in c["address_types"].strip("[]").split(",") if t.strip()]
        # Template compatibility: title field is canonical_address
        c["canonical_address"] = str(c["cluster_key"])
        c["slice_by"] = slice_by
        clusters.append(c)
    return clusters


# Columns that live on Addresses and must be qualified in JOINs (Charities/Grants also have colocator).
_ADDRESSES_COLUMNS = (
    "canonical_address",
    "colocator",
    "zip_code",
    "loose_colocator",
    "latitude",
    "longitude",
    "address_type",
    "owner_id",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "po_box",
)


def _qualify_addresses_expr(expr: str, alias: str = "a") -> str:
    """Prefix Addresses column names so JOINs are unambiguous."""
    out = expr
    for col in sorted(_ADDRESSES_COLUMNS, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(col)}\b", f"{alias}.{col}", out)
    return out


def _member_filter_sql(
    slice_by: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    lat_long: bool = False,
) -> tuple[str, str, str]:
    """Return (key_expr, where, from_join_extra) for per-cluster entity queries.

    from_join_extra is '' , Geocoding LEFT JOIN, or empty for zip (Addresses always `a`).
    Zip uses sargable ``a.zip_code = ?`` — no REGEXP, no Zips re-join (keys already valid).
    """
    mode = resolve_slice_mode(slice_by, conn, lat_long=lat_long)
    if mode.get("needs_geocoding_join") == "1":
        # key/where already use a./g. — do not re-qualify
        return (
            mode["key_expr"],
            mode["where"],
            "LEFT JOIN Geocoding g ON g.geocoding_id = a.geocoding_id",
        )
    if mode.get("uses_alias") == "1":
        # key/where already qualified (e.g. a.zip_code); optional extra joins
        return mode["key_expr"], mode["where"], mode.get("member_join_extra") or ""
    return (
        _qualify_addresses_expr(mode["key_expr"], "a"),
        _qualify_addresses_expr(mode["where"], "a"),
        "",
    )


def fetch_charities(
    conn, slice_by: str, cluster_key: str, top_n: int, *, lat_long: bool = False
) -> list[dict]:
    key_expr, where, gjoin = _member_filter_sql(slice_by, conn, lat_long=lat_long)
    rows = conn.execute(
        f"""
        SELECT DISTINCT c.ein, c.filer_name, c.tax_year, c.receipt_amt, c.grift_ratio, c.domestic_misrep_flag
        FROM Addresses a
        {gjoin}
        JOIN Charities c ON c.charity_id = a.owner_id
        WHERE ({key_expr}) = ?
          AND ({where})
          AND a.address_type = 'charity'
        ORDER BY c.grift_ratio DESC NULLS LAST, c.receipt_amt DESC NULLS LAST
        LIMIT ?
        """,
        [cluster_key, top_n],
    ).fetchall()
    out = []
    for ein, name, year, receipt, grift, misrep in rows:
        misrep_flag = str(misrep or "").upper() in ("TRUE", "1", "Y", "YES", "T")
        out.append({
            "ein": ein, "filer_name": name, "tax_year": year,
            "receipt_amt": receipt, "receipt_fmt": fmt_money(receipt),
            "grift_ratio": grift, "misrep": misrep_flag,
        })
    return out


def fetch_officers(
    conn, slice_by: str, cluster_key: str, top_n: int, *, lat_long: bool = False
) -> list[dict]:
    key_expr, where, gjoin = _member_filter_sql(slice_by, conn, lat_long=lat_long)
    rows = conn.execute(
        f"""
        SELECT DISTINCT o.full_name, o.first_name, o.last_name, o.compensation, o.tax_year
        FROM Addresses a
        {gjoin}
        JOIN Officers o ON o.officer_id = a.owner_id
        WHERE ({key_expr}) = ?
          AND ({where})
          AND a.address_type = 'officer'
        ORDER BY o.compensation DESC NULLS LAST
        LIMIT ?
        """,
        [cluster_key, top_n],
    ).fetchall()
    out = []
    for full, first, last, comp, year in rows:
        display = full or f"{first or ''} {last or ''}".strip()
        out.append({
            "display_name": display, "tax_year": year,
            "compensation": comp, "comp_fmt": fmt_money(comp),
        })
    return out


def fetch_grants(
    conn, slice_by: str, cluster_key: str, top_n: int, *, lat_long: bool = False
) -> list[dict]:
    """Top grants for a cluster, excluding name-suppressed / privacy rollups.

    Over-fetches (up to 10× or 1000) then filters via big_pharma_subsidy patterns
    so the visible top_n are real grantees.
    """
    from grant_suppress import is_suppressed_grantee  # noqa: WPS433

    key_expr, where, gjoin = _member_filter_sql(slice_by, conn, lat_long=lat_long)
    fetch_n = max(top_n * 10, min(1000, top_n * 20))
    # Alias Grants as gr — colocator mode already uses g for Geocoding.
    rows = conn.execute(
        f"""
        SELECT DISTINCT gr.filer_ein, gr.grantee_name, gr.grant_amt, gr.tax_year
        FROM Addresses a
        {gjoin}
        JOIN Grants gr ON gr.grant_id = a.owner_id
        WHERE ({key_expr}) = ?
          AND ({where})
          AND a.address_type = 'grant'
        ORDER BY gr.grant_amt DESC NULLS LAST
        LIMIT ?
        """,
        [cluster_key, fetch_n],
    ).fetchall()
    out = [
        {
            "filer_ein": fe, "grantee_name": gn, "grant_amt": amt,
            "amt_fmt": fmt_money(amt), "tax_year": yr,
        }
        for fe, gn, amt, yr in rows
        if not is_suppressed_grantee(gn)
    ]
    return out[:top_n]


def fetch_dot_carriers(
    conn, slice_by: str, cluster_key: str, top_n: int, *, lat_long: bool = False
) -> list[dict]:
    key_expr, where, gjoin = _member_filter_sql(slice_by, conn, lat_long=lat_long)
    rows = conn.execute(
        f"""
        SELECT DISTINCT
            d.dot_number, d.legal_name, d.dba_name, d.status_code, d.power_units, d.phone,
            a.canonical_address
        FROM Addresses a
        {gjoin}
        JOIN dot_carriers d ON d.id = a.owner_id
        WHERE ({key_expr}) = ?
          AND ({where})
          AND a.address_type = 'dot_carrier_phy'
        ORDER BY d.power_units DESC NULLS LAST, d.legal_name
        LIMIT ?
        """,
        [cluster_key, top_n],
    ).fetchall()
    return [
        {
            "dot_number": dot, "legal_name": legal, "dba_name": dba,
            "status_code": status, "power_units": pu, "phone": phone,
            "canonical_address": (canon or "").strip() or "(no street address)",
        }
        for dot, legal, dba, status, pu, phone, canon in rows
    ]


def fetch_address_subgroups(
    conn,
    slice_by: str,
    cluster_key: str,
    *,
    lat_long: bool = False,
    max_addresses: int = 200,
) -> list[dict]:
    """Distinct canonical_address breakdown inside a non-address cluster.

    Surfaces suite / building / PO-box splits within colocator, zip, or loose grid.
    """
    if slice_by == "address":
        return []
    key_expr, where, gjoin = _member_filter_sql(slice_by, conn, lat_long=lat_long)
    rows = conn.execute(
        f"""
        WITH members AS (
            SELECT
                COALESCE(NULLIF(TRIM(a.canonical_address), ''), '(no street address)') AS addr,
                a.address_type,
                a.owner_id
            FROM Addresses a
            {gjoin}
            WHERE ({key_expr}) = ?
              AND ({where})
        ),
        base AS (
            SELECT
                addr AS canonical_address,
                COUNT(*)::BIGINT AS total_rows,
                COUNT(DISTINCT address_type)::BIGINT AS multi_type_count,
                LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
                SUM(CASE WHEN address_type = 'dot_carrier_phy'
                         THEN 1 ELSE 0 END)::BIGINT AS dot_carrier_count,
                SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_count,
                SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_count,
                SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_count
            FROM members
            GROUP BY addr
        ),
        dot_stats AS (
            SELECT
                m.addr AS canonical_address,
                SUM(CASE WHEN d.status_code = 'A' THEN 1 ELSE 0 END)::BIGINT AS dot_active_count,
                SUM(CASE WHEN d.status_code = 'I' THEN 1 ELSE 0 END)::BIGINT AS dot_inactive_count,
                SUM(CASE WHEN d.status_code = 'A' THEN COALESCE(d.power_units, 0) ELSE 0 END)::BIGINT
                    AS active_power_units,
                SUM(CASE WHEN d.status_code = 'I' THEN COALESCE(d.power_units, 0) ELSE 0 END)::BIGINT
                    AS inactive_power_units
            FROM members m
            INNER JOIN dot_carriers d ON d.id = m.owner_id
                AND m.address_type = 'dot_carrier_phy'
            GROUP BY m.addr
        )
        SELECT
            b.canonical_address,
            b.total_rows,
            b.multi_type_count,
            b.address_types,
            b.dot_carrier_count,
            b.charity_count,
            b.grant_count,
            b.officer_count,
            COALESCE(ds.dot_active_count, 0),
            COALESCE(ds.dot_inactive_count, 0),
            COALESCE(ds.active_power_units, 0),
            COALESCE(ds.inactive_power_units, 0)
        FROM base b
        LEFT JOIN dot_stats ds ON ds.canonical_address = b.canonical_address
        ORDER BY b.dot_carrier_count DESC, b.multi_type_count DESC,
                 b.total_rows DESC, b.canonical_address
        LIMIT ?
        """,
        [cluster_key, max_addresses],
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        (
            addr, total, multi, types, dots, charities, grants, officers,
            act_n, ina_n, act_pu, ina_pu,
        ) = row
        if isinstance(types, str):
            type_list = [t.strip() for t in types.strip("[]").split(",") if t.strip()]
        elif types is None:
            type_list = []
        else:
            type_list = list(types)
        out.append({
            "canonical_address": addr,
            "total_rows": int(total or 0),
            "multi_type_count": int(multi or 0),
            "address_types": type_list,
            "dot_carrier_count": int(dots or 0),
            "charity_count": int(charities or 0),
            "grant_count": int(grants or 0),
            "officer_count": int(officers or 0),
            "dot_active_count": int(act_n or 0),
            "dot_inactive_count": int(ina_n or 0),
            "active_power_units": int(act_pu or 0),
            "inactive_power_units": int(ina_pu or 0),
            "maps_url": google_maps_url(addr) if addr and not addr.startswith("(") else "",
            "phy_is_po_box": is_po_box(addr),
        })
    return out


def group_dot_by_address(dot_carriers: list[dict]) -> list[dict]:
    """Group DOT carriers by street address; sort by total power units (desc)."""
    groups: dict[str, list] = defaultdict(list)
    for d in dot_carriers:
        addr = d.get("canonical_address") or "(no street address)"
        groups[addr].append(d)
    out: list[dict] = []
    for addr, carriers in sorted(
        groups.items(),
        key=lambda item: sum(x.get("power_units") or 0 for x in item[1]),
        reverse=True,
    ):
        out.append({
            "canonical_address": addr,
            "carriers": carriers,
            "maps_url": (
                google_maps_url(addr)
                if addr and not str(addr).startswith("(")
                else ""
            ),
            "phy_is_po_box": is_po_box(addr),
        })
    return out


def render_template(name: str, **kwargs) -> str:
    from mako.lookup import TemplateLookup

    lookup = TemplateLookup(
        directories=[str(SCRIPT_DIR / "templates")],
        input_encoding="utf-8",
    )
    tpl = lookup.get_template(name)
    return tpl.render(css=CSS, **kwargs)


def write_report(
    db_path: str,
    output_dir: Path,
    slice_by: str,
    min_multi_type: int,
    min_dot_carriers: int,
    require_grift_signal: bool,
    top_n: int,
    max_clusters: int,
    physical_notes_path: Path,
    include_officers: bool,
    include_grants: bool,
    *,
    lat_long: bool = False,
) -> int:
    if slice_by not in SLICE_MODES:
        raise ValueError(f"Unknown slice-by {slice_by!r}; choose from {list(SLICE_MODES)}")
    if lat_long and slice_by != "colocator":
        raise ValueError("--lat-long only applies with --slice-by colocator")

    conn = duckdb.connect(db_path, read_only=True)
    try:
        mode = resolve_slice_mode(slice_by, conn, lat_long=lat_long)
        output_dir.mkdir(parents=True, exist_ok=True)
        data_dir = output_dir / "data"
        data_dir.mkdir(exist_ok=True)

        notes = load_physical_notes(physical_notes_path)
        generated_at = datetime.now().isoformat(timespec="seconds")
        report_date = date.today().isoformat()

        from domain_briefing import (  # noqa: WPS433
            annotate_cluster_percentile_chips,
            cutpoints_for_focus,
            ensure_population_cutpoints,
            index_methodology_context,
        )

        pop_cache = ensure_population_cutpoints(conn)
        pop_cutpoints = cutpoints_for_focus("dot", pop_cache)

        clusters_raw = fetch_clusters(
            conn,
            slice_by,
            min_multi_type,
            min_dot_carriers,
            require_grift_signal,
            max_clusters,
            lat_long=lat_long,
        )
        if not clusters_raw:
            print("No clusters matched selection criteria.")
            return 0

        clusters_out = []
        for c in clusters_raw:
            key = str(c["cluster_key"])
            sample = c.get("sample_address") or key
            slug = slugify_address(f"{slice_by}-{key}")
            detail_file = f"{slug}.html"

            dot_carriers_full = fetch_dot_carriers(
                conn, slice_by, key, 9999, lat_long=lat_long
            )

            active_count = sum(1 for d in dot_carriers_full if d.get("status_code") == "A")
            inactive_count = sum(1 for d in dot_carriers_full if d.get("status_code") == "I")
            active_power = sum(d.get("power_units") or 0 for d in dot_carriers_full if d.get("status_code") == "A")
            inactive_power = sum(d.get("power_units") or 0 for d in dot_carriers_full if d.get("status_code") == "I")

            phy_is_po_box = is_po_box(sample) or (
                slice_by == "colocator" and key.upper().startswith("PO:")
            )

            c["dot_active_count"] = active_count
            c["dot_inactive_count"] = inactive_count
            c["dot_active_power_units"] = active_power
            c["dot_inactive_power_units"] = inactive_power
            c["ia_ratio"] = (
                round(inactive_count / (active_count + inactive_count), 3)
                if (active_count + inactive_count) > 0
                else 0
            )
            c["inactive_pct"] = round(c["ia_ratio"] * 100, 1)
            c["phy_is_po_box"] = phy_is_po_box
            c["suspicion_score"] = suspicion_score(c)
            # Suite rank: physical DOT records, then distinct address types.
            types_n = int(c.get("multi_type_count") or 0)
            dots_n = int(c.get("dot_carrier_count") or 0)
            c["rank_metric_value"] = dots_n * 100 + types_n
            c["rank_metric_fmt"] = f"{dots_n:,} · {types_n} types"
            c["reason_codes"] = reason_codes(c, min_multi_type, min_dot_carriers)
            c["maps_url"] = google_maps_url(sample, zoom=17)
            c["detail_file"] = detail_file
            c["slug"] = slug
            c["sample_address"] = sample
            c["percentile_chips"] = annotate_cluster_percentile_chips(
                c, "dot", pop_cutpoints
            )
            # Index/detail title
            if slice_by == "address":
                c["canonical_address"] = key
            else:
                c["canonical_address"] = f"{key}  ·  e.g. {sample}" if sample != key else key
            clusters_out.append(c)

            charities = fetch_charities(conn, slice_by, key, top_n, lat_long=lat_long)
            officers = (
                fetch_officers(conn, slice_by, key, top_n, lat_long=lat_long)
                if include_officers
                else []
            )
            grants = (
                fetch_grants(conn, slice_by, key, top_n, lat_long=lat_long)
                if include_grants
                else []
            )
            dot_carriers_display = fetch_dot_carriers(
                conn, slice_by, key, top_n, lat_long=lat_long
            )

            phone_groups: dict[str, list] = defaultdict(list)
            for d in dot_carriers_full:
                phone = d.get("phone") or "No Phone"
                phone_groups[phone].append(d)

            phone_groups_sorted = sorted(
                phone_groups.items(),
                key=lambda item: sum(x.get("power_units") or 0 for x in item[1]),
                reverse=True,
            )

            # Break carriers into street-address groups (always useful) and, for
            # non-address slices, also list every distinct canonical_address in
            # the cluster (suites / multi-street shells).
            address_subgroups: list[dict] = []
            address_groups_sorted = group_dot_by_address(dot_carriers_full)
            if slice_by != "address":
                address_subgroups = fetch_address_subgroups(
                    conn, slice_by, key, lat_long=lat_long
                )
            c["distinct_address_count"] = (
                len(address_subgroups)
                if address_subgroups
                else (1 if slice_by == "address" else len(address_groups_sorted) or 0)
            )

            from cluster_table_payload import (  # noqa: WPS433
                build_detail_tables,
                dumps_table_json,
            )

            detail_tables = build_detail_tables(
                charities=charities,
                officers=officers,
                grants=grants,
                address_subgroups=address_subgroups if slice_by != "address" else None,
                phone_groups=phone_groups_sorted,
                address_groups=address_groups_sorted,
            )
            from map_points import (  # noqa: WPS433
                clusters_to_map_points,
                single_point_from_key,
            )

            detail_map = clusters_to_map_points([c], slice_by=slice_by) or single_point_from_key(
                key,
                label=c.get("canonical_address") or key,
                slice_by=slice_by,
                sample_address=sample,
            )
            from breadcrumbs import crumbs_national_detail  # noqa: WPS433
            from widen_links import build_widen_links  # noqa: WPS433

            report_day = report_date
            reports_root = SCRIPT_DIR / "reports"
            widen_links = build_widen_links(
                focus="dot",
                slice_by=slice_by,
                cluster_key=key,
                sample_address=sample,
                report_day=report_day,
                reports_dir=reports_root,
                output_dir=output_dir,
                conn=conn,
                lat_long=lat_long,
                context="national",
            )
            html = render_template(
                "address_cluster_detail.mako",
                cluster=c,
                charities=charities,
                officers=officers,
                grants=grants,
                dot_carriers=dot_carriers_display,
                phone_groups=phone_groups_sorted,
                address_subgroups=address_subgroups,
                address_groups=address_groups_sorted,
                show_address_subgroups=(slice_by != "address"),
                physical_note=physical_note_for(sample, notes) or physical_note_for(key, notes),
                generated_at=generated_at,
                detail_tables_json=dumps_table_json(detail_tables),
                map_points=detail_map,
                breadcrumbs=crumbs_national_detail(
                    focus="dot",
                    slice_by=slice_by,
                    detail_label=str(c.get("canonical_address") or key),
                ),
                widen_links=widen_links,
            )
            (output_dir / detail_file).write_text(html, encoding="utf-8")

            json_data = {
                "slug": slug,
                "slice_by": slice_by,
                "cluster_key": key,
                "sample_address": sample,
                "canonical_address": c.get("canonical_address"),
                "suspicion_score": c.get("suspicion_score"),
                "dot_carrier_count": c.get("dot_carrier_count"),
                "active_power_units": c.get("dot_active_power_units"),
                "inactive_power_units": c.get("dot_inactive_power_units"),
                "ia_ratio": c.get("ia_ratio"),
                "distinct_address_count": c.get("distinct_address_count"),
                "physical_note": physical_note_for(sample, notes),
                "address_subgroups": address_subgroups,
                "address_groups": [],
                "phone_groups": [],
                "generated_at": generated_at,
            }

            for ag in address_groups_sorted:
                carriers = ag["carriers"]
                active = [d for d in carriers if d.get("status_code") == "A"]
                inactive = [d for d in carriers if d.get("status_code") != "A"]
                json_data["address_groups"].append({
                    "canonical_address": ag["canonical_address"],
                    "maps_url": ag.get("maps_url"),
                    "total_power_units": sum((d.get("power_units") or 0) for d in carriers),
                    "active_count": len(active),
                    "inactive_count": len(inactive),
                    "active": active,
                    "inactive": inactive,
                })

            for phone, carriers in phone_groups_sorted:
                active = [d for d in carriers if d.get("status_code") == "A"]
                inactive = [d for d in carriers if d.get("status_code") != "A"]
                json_data["phone_groups"].append({
                    "phone": phone,
                    "total_power_units": sum((d.get("power_units") or 0) for d in carriers),
                    "active_count": len(active),
                    "inactive_count": len(inactive),
                    "active": active,
                    "inactive": inactive,
                })

            json_path = data_dir / f"{slug}.json"
            json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

        from cluster_table_payload import (  # noqa: WPS433
            build_dot_cluster_table,
            dumps_table_json,
        )

        # Ensure active_power_units is set for table (alias from enrich fields)
        for c in clusters_out:
            if c.get("active_power_units") is None:
                c["active_power_units"] = c.get("dot_active_power_units") or 0

        table_payload = build_dot_cluster_table(
            clusters_out, min_dot_carriers=min_dot_carriers
        )
        from map_points import clusters_to_map_points  # noqa: WPS433

        map_points = clusters_to_map_points(clusters_out, slice_by=slice_by)
        from breadcrumbs import crumbs_national_index  # noqa: WPS433

        methodology = index_methodology_context("dot", pop_cutpoints)
        index_html = render_template(
            "address_cluster_index.mako",
            clusters=clusters_out,
            cluster_count=len(clusters_out),
            generated_at=generated_at,
            report_date=report_date,
            db_path=db_path,
            min_multi_type=min_multi_type,
            min_dot_carriers=min_dot_carriers,
            require_grift_signal=require_grift_signal,
            slice_by=slice_by,
            slice_label=mode["label"],
            cluster_table_json=dumps_table_json(table_payload),
            map_points=map_points,
            breadcrumbs=crumbs_national_index(focus="dot", slice_by=slice_by),
            methodology=methodology,
            rank_label="DOT records · types",
        )
        if map_points:
            (data_dir / "map_points.json").write_text(
                json.dumps(map_points, indent=2), encoding="utf-8"
            )
        (output_dir / "index.html").write_text(index_html, encoding="utf-8")

        serializable = []
        for c in clusters_out:
            row = {k: v for k, v in c.items() if k != "address_types"}
            row["address_types"] = list(c["address_types"])
            serializable.append(row)
        with open(data_dir / "clusters.json", "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)

        metadata = {
            "generated_at": generated_at,
            "db_path": db_path,
            "focus": "dot",
            "slice_by": slice_by,
            "slice_label": mode["label"],
            "lat_long": lat_long,
            "criteria": {
                "min_multi_type": min_multi_type,
                "min_dot_carriers": min_dot_carriers,
                "require_grift_signal": require_grift_signal,
                "top_n_entities": top_n,
                "max_clusters": max_clusters,
                "lat_long": lat_long,
            },
            "cluster_count": len(clusters_out),
            "population_cutpoints": pop_cutpoints,
            "population_cutpoints_generated_at": pop_cache.get("generated_at"),
            "methodology": {
                "question": methodology.get("question"),
                "signals": methodology.get("signals"),
                "rank": methodology.get("rank"),
            },
        }
        with open(output_dir / "export_metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        ll_note = " `--lat-long` (LL: only)" if lat_long else ""
        readme = f"""# Cluster Report — {mode['label']} — {report_date}

Static HTML drill-down grouped by **{mode['label']}** (`--slice-by {slice_by}`{ll_note}).

- Open `index.html` in a browser (no server required).
- Map links use a sample street address from the cluster when the key is not a street.
- Criteria in `export_metadata.json`.

Generated: {generated_at}
Clusters: {len(clusters_out)}
DB: {db_path}
"""
        (output_dir / "README.md").write_text(readme, encoding="utf-8")

        print(f"Wrote {len(clusters_out)} cluster pages to {output_dir}")
        print(f"  slice-by: {slice_by} ({mode['label']})")
        if lat_long:
            print("  lat-long: LL: only (PO/FA/… excluded)")
        print(f"  index: {output_dir / 'index.html'}")
        return len(clusters_out)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate static address/colocator/zip/loose cluster HTML reports"
    )
    parser.add_argument("--db-path", default=os.environ.get("IRS990_DB_PATH", DEFAULT_DB))
    parser.add_argument(
        "--slice-by",
        choices=list(SLICE_MODES.keys()),
        default="address",
        help="Cluster key: address (default), colocator, zipcode, loose_colocator",
    )
    parser.add_argument(
        "--lat-long",
        "--lat_long",
        dest="lat_long",
        action="store_true",
        help="With --slice-by colocator: only LL:lat:lon keys (exclude PO:/FA:/…)",
    )
    parser.add_argument("--output-dir", help="Output folder (default: reports/<slice>_YYYY-MM-DD)")
    parser.add_argument("--physical-notes", default=str(SCRIPT_DIR / "physical_notes.json"))
    parser.add_argument(
        "--min-multi-type",
        type=int,
        default=0,
        help="Deprecated optional floor on address_types (0=off)",
    )
    parser.add_argument(
        "--min-dot-carriers",
        type=int,
        default=0,
        help="Deprecated optional floor on phy carriers (0=off). "
        "Suite size is max_clusters after rank.",
    )
    parser.add_argument(
        "--require-grift-signal",
        action="store_true",
        help="Unused in practice (grift_ratio not populated); leave off.",
    )
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument(
        "--max-clusters",
        type=int,
        default=100,
        help="Keep top N clusters after rank (the real suite cap)",
    )
    parser.add_argument("--no-officers", action="store_true")
    parser.add_argument("--no-grants", action="store_true")
    args = parser.parse_args()

    if args.lat_long and args.slice_by != "colocator":
        raise SystemExit("--lat-long only applies with --slice-by colocator")

    # Resolve output prefix (may be colocator_ll_clusters when lat_long)
    # Stable path (no date) for public deploy — pass --output-dir to override.
    prefix = resolve_slice_mode(args.slice_by, lat_long=args.lat_long)["out_dir_prefix"]
    out = (
        Path(args.output_dir)
        if args.output_dir
        else SCRIPT_DIR / "reports" / prefix
    )
    if not os.path.exists(args.db_path):
        raise SystemExit(f"Database not found: {args.db_path}")

    write_report(
        db_path=args.db_path,
        output_dir=out,
        slice_by=args.slice_by,
        min_multi_type=args.min_multi_type,
        min_dot_carriers=args.min_dot_carriers,
        require_grift_signal=args.require_grift_signal,
        top_n=args.top_n,
        max_clusters=args.max_clusters,
        physical_notes_path=Path(args.physical_notes),
        include_officers=not args.no_officers,
        include_grants=not args.no_grants,
        lat_long=args.lat_long,
    )


if __name__ == "__main__":
    main()
