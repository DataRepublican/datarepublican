#!/usr/bin/env python3
"""OFAC SDN co-location reports — isolated package for Treasury review.

Surfaces locations where an OFAC-listed entity shares a physical footprint
with IRS 990 charities/grants/officers/contractors, DOT carriers, FEC money,
or Medicare/NPPES providers.

Slices
  colocator       — tight building / PO (Addresses+Geocoding); **excludes FA: country-only**
  loose_colocator — 0.5° LL grid (wider neighborhood; same key as grant_match loose)
  address         — exact canonical_address (strongest same-building / mail-drop signal)
  zipcode         — valid US ZIP via Zips catalog (widen only; noisier)

All queries are read-only. Output is static HTML under ofac_reporting/reports/.

Usage:
  python ofac_reporting/generate_ofac_reports.py
  python ofac_reporting/generate_ofac_reports.py --slice-by colocator --max-clusters 50
  python ofac_reporting/generate_ofac_reports.py --all-slices
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DOT_REPORTING = REPO_ROOT / "dot_reporting"
if str(DOT_REPORTING) not in sys.path:
    sys.path.insert(0, str(DOT_REPORTING))

DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb"

# Co-tenant types we care about for Treasury packaging
COTENANT_TYPES = (
    "charity",
    "grant",
    "officer",
    "contractor",
    "dot_carrier_phy",
    "dot_carrier_mail",
    "fec_contributor",
    "fec_committee",
    "fec_committee_transaction",
    "fec_operating_expenditure",
    "fec_candidate_spending",
    "nppes_practice",
    "nppes_mailing",
    "bmf",
)

CSS = """
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, sans-serif; margin: 1.5rem; color: #1a1a1a;
  line-height: 1.45; max-width: 1100px; }
header h1 { margin-bottom: 0.25rem; }
.meta { color: #555; font-size: 0.9rem; }
.banner {
  background: #1e3a5f; color: #f8fafc; padding: 0.85rem 1rem; border-radius: 8px;
  margin: 0 0 1.25rem; font-size: 0.92rem;
}
.banner strong { color: #fff; }
.banner a { color: #93c5fd; }
nav.crumbs { margin: 0 0 1rem; font-size: 0.88rem; color: #555; line-height: 1.5; }
nav.crumbs a { color: #0b57d0; text-decoration: none; font-weight: 500; }
nav.crumbs a:hover { text-decoration: underline; }
nav.crumbs .bc-sep { margin: 0 0.35rem; color: #9ca3af; }
nav.crumbs .bc-current { color: #111; font-weight: 600; }
.chips { margin: 0.75rem 0; }
.chip { display: inline-block; background: #e8f0fe; color: #174ea6;
  padding: 0.2rem 0.55rem; border-radius: 999px; font-size: 0.8rem; margin: 0 0.35rem 0.35rem 0; }
.chip.ofac { background: #7f1d1d; color: #fef2f2; }
.chip.warn { background: #fef3c7; color: #92400e; }
.cards { display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 1rem 0; }
.card { background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 8px;
  padding: 0.75rem 1rem; min-width: 100px; }
.card strong { display: block; font-size: 1.3rem; }
.card span { font-size: 0.78rem; color: #666; }
table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.86rem; }
th, td { border: 1px solid #ddd; padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }
th { background: #f4f4f4; position: sticky; top: 0; }
tr:nth-child(even) { background: #fafafa; }
tr.ofac-row { background: #fef2f2 !important; }
a { color: #0b57d0; }
.section { margin: 1.5rem 0; }
.section h2 { border-bottom: 2px solid #1e3a5f; padding-bottom: 0.3rem; font-size: 1.15rem; }
.note { background: #f0f7ff; border-left: 4px solid #1e3a5f; padding: 0.75rem 1rem; margin: 1rem 0; font-size: 0.9rem; }
footer { margin-top: 2rem; color: #666; font-size: 0.85rem; border-top: 1px solid #e5e7eb; padding-top: 1rem; }
.disclaimer { font-size: 0.82rem; color: #6b7280; max-width: 50rem; }
@media (max-width: 700px) { body { margin: 0.75rem; } table { font-size: 0.78rem; } }
"""


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def fmt_money(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B"
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"${n/1_000:.1f}K"
    return f"${n:,.0f}"


def slugify(s: str, max_len: int = 80) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "").strip().lower()).strip("-")
    return (s[:max_len] or "cluster").strip("-")


def maps_url(addr: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(addr or "")


def normalize_ein9(raw: Any) -> str | None:
    """Digits-only EIN; return 9-char string or None."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 9:
        return digits
    # rare padded forms e.g. 000920912 already 9
    if len(digits) > 9 and digits.lstrip("0") and len(digits[-9:]) == 9:
        return digits[-9:]
    return None


def fmt_ein(ein9: str | None) -> str:
    if not ein9 or len(ein9) != 9:
        return "—"
    return f"{ein9[:2]}-{ein9[2:]}"


def propublica_url(ein9: str) -> str:
    """ProPublica Nonprofit Explorer (990 filers). EIN digits only, no hyphen."""
    return f"https://projects.propublica.org/nonprofits/organizations/{ein9}"


def ein_link_html(
    ein9: str | None,
    *,
    is_filer: bool = False,
    is_bmf: bool = False,
) -> str:
    """Link EIN only when it appears in IRS data.

    - 990 filer (Charities) → ProPublica Nonprofit Explorer
    - BMF only → local EIN detail page
    - Neither → plain text (OFAC tax ID for a business, not an exempt org)
    """
    if not ein9:
        return "—"
    label = fmt_ein(ein9)
    if is_filer:
        return (
            f'<a href="{esc(propublica_url(ein9))}" target="_blank" rel="noopener" '
            f'title="ProPublica Nonprofit Explorer">{esc(label)}</a>'
        )
    if is_bmf:
        return f'<a href="../eins/{esc(ein9)}.html">{esc(label)}</a>'
    return f"<code>{esc(label)}</code>"


def dot_link_html(dot_number: Any) -> str:
    """Same SC + map + MOTUS links as dot_reporting cluster tables."""
    d = re.sub(r"\D", "", str(dot_number or ""))
    if not d:
        return "—"
    de = esc(d)
    return (
        f'<a href="https://searchcarriers.com/company/{de}" target="_blank" rel="noopener">{de}</a> '
        f'<small>['
        f'<a href="https://searchcarriers.com/company/{de}" target="_blank" rel="noopener">SC</a>] '
        f'[<a href="https://searchcarriers.com/map/company/{de}" target="_blank" rel="noopener" '
        f'title="Search Carriers map" aria-label="Search Carriers map">🌐</a>] '
        f'[<a href="https://motus.dot.gov/customer/{de}/account" target="_blank" rel="noopener">MOTUS</a>]'
        f"</small>"
    )


# US states + DC/territories used for footprint gate (not city names like London).
US_STATE_SET = set(
    (
        "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD "
        "MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC "
        "SD TN TX UT VT VA WA WV WI WY DC PR VI GU AS MP"
    ).split()
)


def is_street_quality_address(addr: str | None) -> bool:
    """True for real street / PO-with-zip samples — not city-only shells.

    Rejects: Dubai, Miami Fl 33102 (no street #), bare city names.
    Does **not** by itself require US — see is_us_street_address().
    """
    a = (addr or "").strip()
    if len(a) < 10 or "," not in a:
        return False
    # PO Box … need a 5-digit zip somewhere
    if re.match(r"^(P\.?\s*O\.?\s*Box|Post\s+Office\s+Box)\s+\d+", a, re.I):
        return bool(re.search(r"\b\d{5}\b", a))
    # Street number required at start (not "Miami, Fl, 33102")
    if not re.match(r"^\d+", a):
        return False
    first = a.split(",", 1)[0].strip()
    if len(first) < 6:
        return False
    if not re.search(r"[A-Za-z]", first):
        return False
    if a.count(",") < 2:
        return False
    return True


# Foreign tokens that sometimes ride a 5-digit code colliding with a real US ZIP
# (e.g. Phnom Penh 12201 ≡ Albany NY ZCTA).
_FOREIGN_ADDR_MARKERS = re.compile(
    r"\b("
    r"phnom\s*penh|sangkat|monivong|cambodia|kampuchea|"
    r"london|manchester|birmingham|glasgow|edinburgh|"
    r"hong\s*kong|shanghai|beijing|shenzhen|tokyo|osaka|"
    r"dubai|abu\s*dhabi|singapore|bangkok|hanoi|saigon|"
    r"moscow|kyiv|kiev|minsk|tehran|baghdad|beirut|damascus|"
    r"karachi|lahore|islamabad|delhi|mumbai|chennai|"
    r"toronto|vancouver|montreal|ottawa|"
    r"sydney|melbourne|auckland|"
    r"paris|lyon|berlin|munich|frankfurt|amsterdam|rotterdam|"
    r"brussels|geneva|zurich|vienna|rome|milan|madrid|barcelona|"
    r"stockholm|oslo|copenhagen|helsinki|warsaw|prague|"
    r"mexico\s*city|guadalajara|monterrey|bogota|lima|santiago|"
    r"nicicosia|nicosia|istanbul|ankara"
    r")\b",
    re.I,
)


def is_us_street_address(addr: str | None) -> bool:
    """Street-quality **and** US state + ZIP5 (drops London / Phnom Penh / etc.).

    Accepts: '…, New York, Ny, 10017', '…, Bridgeview, Il, 60455'
    Rejects:
      - '27 Old Gloucester Street, London, 13' (no US ST+ZIP5)
      - 'Po Box 1131, … Phnom Penh, 12201' (foreign city; 12201 collides with US ZIP)
    """
    if not is_street_quality_address(addr):
        return False
    a = (addr or "").strip()
    if _FOREIGN_ADDR_MARKERS.search(a):
        return False
    # ", ST, 12345" or ", ST 12345" near end — state must be US
    m = re.search(
        r",\s*([A-Za-z]{2})\s*,\s*(\d{5})(?:-\d{4})?\s*$",
        a,
    )
    if m and m.group(1).upper() in US_STATE_SET:
        return True
    m = re.search(r",\s*([A-Za-z]{2})\s+(\d{5})(?:-\d{4})?\s*$", a)
    if m and m.group(1).upper() in US_STATE_SET:
        return True
    return False


# SQL: US footprint — **state required**. Zip∈Zips alone is insufficient:
# foreign 5-digit postcodes (e.g. Phnom Penh 12201) collide with real US ZCTAs.
_US_FOOTPRINT_SQL_A = """(
    a.state IS NOT NULL
    AND length(trim(a.state)) = 2
    AND upper(trim(a.state)) IN ({states})
)""".format(
    states=", ".join(f"'{s}'" for s in sorted(US_STATE_SET))
)


def is_quality_colocator_key(key: str | None) -> bool:
    """LL:lat:lon or PO:box:zip5 only — no VENDOR, bare PO, FA, junk."""
    k = (key or "").strip()
    if k.upper().startswith("VENDOR"):
        return False
    if k.startswith("LL:"):
        parts = k.split(":")
        if len(parts) < 3:
            return False
        try:
            float(parts[1])
            float(parts[2])
            return True
        except (TypeError, ValueError):
            return False
    # PO:box:##### only (zip required)
    return bool(re.match(r"^PO:[^:]+:[0-9]{5}$", k, re.I))


def is_quality_loose_key(key: str | None) -> bool:
    """0.5° grid key: LL:lat:lon only (half-degree cells)."""
    k = (key or "").strip()
    if not k.startswith("LL:"):
        return False
    parts = k.split(":")
    if len(parts) < 3:
        return False
    try:
        float(parts[1])
        float(parts[2])
        return True
    except (TypeError, ValueError):
        return False


def effective_loose_colocator_expr(alias_a: str = "a", alias_g: str = "g") -> str:
    """Prefer stored loose_colocator; else derive half-degree LL: from lat/lon."""
    return f"""COALESCE(
        NULLIF(TRIM({alias_a}.loose_colocator), ''),
        CASE
            WHEN {alias_g}.latitude IS NOT NULL AND {alias_g}.longitude IS NOT NULL
            THEN 'LL:' || CAST(ROUND({alias_g}.latitude / 0.5) * 0.5 AS VARCHAR)
                 || ':' || CAST(ROUND({alias_g}.longitude / 0.5) * 0.5 AS VARCHAR)
        END,
        CASE
            WHEN {alias_a}.latitude IS NOT NULL AND {alias_a}.longitude IS NOT NULL
            THEN 'LL:' || CAST(ROUND({alias_a}.latitude / 0.5) * 0.5 AS VARCHAR)
                 || ':' || CAST(ROUND({alias_a}.longitude / 0.5) * 0.5 AS VARCHAR)
        END
    )"""


# SQL predicate: street-ish canonical (used for colocator quality gate)
_STREET_QUALITY_SQL = """(
    (
        regexp_matches(TRIM(COALESCE(canonical_address, '')), '^[0-9].*[A-Za-z]')
        AND length(trim(split_part(canonical_address, ',', 1))) >= 6
        AND canonical_address LIKE '%,%,%'
    )
    OR (
        regexp_matches(upper(TRIM(COALESCE(canonical_address, ''))),
                       '^P\\.?O\\.?[[:space:]]*BOX[[:space:]]+[0-9]')
        AND regexp_matches(COALESCE(canonical_address, ''), '[0-9]{5}')
    )
)"""


def type_in_sql(types: tuple[str, ...], col: str) -> str:
    return f"{col} IN (" + ", ".join("'" + t.replace("'", "''") + "'" for t in types) + ")"


def effective_colocator_expr(alias_a: str = "a", alias_g: str = "g") -> str:
    return (
        f"COALESCE(NULLIF(TRIM({alias_a}.colocator), ''), "
        f"NULLIF(TRIM({alias_g}.colocator), ''))"
    )


def open_db(path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path, read_only=True)


# ---------------------------------------------------------------------------
# Cluster ranking
# ---------------------------------------------------------------------------

def fetch_clusters(
    con: duckdb.DuckDBPyConnection,
    slice_by: str,
    *,
    max_clusters: int,
) -> list[dict[str, Any]]:
    """Locations with ≥1 ofac_sanction and ≥1 co-tenant type."""
    cot = type_in_sql(COTENANT_TYPES, "address_type")
    ofac = "address_type = 'ofac_sanction'"

    if slice_by == "colocator":
        colo = effective_colocator_expr("a", "g")
        key_ok = f"""
          ({colo}) IS NOT NULL
          AND TRIM(CAST(({colo}) AS VARCHAR)) != ''
          AND (
                ({colo}) LIKE 'LL:%'
             OR regexp_matches(CAST(({colo}) AS VARCHAR), '^PO:[^:]+:[0-9]{{5}}$')
          )
          AND ({colo}) NOT LIKE 'FA:%'
          AND ({colo}) NOT LIKE 'VENDOR:%'
          AND ({colo}) NOT LIKE 'grok:%'
          AND ({colo}) NOT LIKE 'PARTIAL:%'
          AND ({colo}) NOT LIKE 'BOGUS:%'
          AND ({colo}) NOT LIKE '%{{zip}}%'
          AND ({colo}) NOT ILIKE '%UNKN%'
          AND ({colo}) NOT ILIKE '%VAGUE%'
        """
        # Seed from OFAC rows only (~27k), then join co-tenants at those keys.
        # US state required on seed (zip-in-Zips alone is wrong for Phnom Penh 12201 etc.).
        sql = f"""
        WITH ofac_keys AS (
            SELECT DISTINCT ({colo}) AS cluster_key
            FROM Addresses a
            LEFT JOIN Geocoding g ON g.geocoding_id = a.geocoding_id
            WHERE a.address_type = 'ofac_sanction'
              AND {key_ok}
              AND {_US_FOOTPRINT_SQL_A}
        ),
        keyed AS (
            SELECT
                ({colo}) AS cluster_key,
                a.address_type AS address_type,
                a.owner_id AS owner_id,
                a.canonical_address AS canonical_address
            FROM Addresses a
            LEFT JOIN Geocoding g ON g.geocoding_id = a.geocoding_id
            INNER JOIN ofac_keys k ON k.cluster_key = ({colo})
            WHERE {key_ok}
        ),
        base AS (
            SELECT
                cluster_key,
                COUNT(*)::BIGINT AS total_rows,
                COUNT(DISTINCT address_type)::BIGINT AS multi_type_count,
                LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
                SUM(CASE WHEN {ofac} THEN 1 ELSE 0 END)::BIGINT AS ofac_n,
                COUNT(DISTINCT CASE WHEN {ofac} THEN owner_id END)::BIGINT AS ofac_entities,
                SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_n,
                SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_n,
                SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_n,
                SUM(CASE WHEN address_type = 'contractor' THEN 1 ELSE 0 END)::BIGINT AS contractor_n,
                SUM(CASE WHEN address_type IN ('dot_carrier_phy','dot_carrier_mail')
                         THEN 1 ELSE 0 END)::BIGINT AS dot_n,
                SUM(CASE WHEN address_type LIKE 'fec%' THEN 1 ELSE 0 END)::BIGINT AS fec_n,
                SUM(CASE WHEN address_type IN ('nppes_practice','nppes_mailing')
                         THEN 1 ELSE 0 END)::BIGINT AS medicare_n,
                SUM(CASE WHEN {cot} THEN 1 ELSE 0 END)::BIGINT AS cotenant_n,
                max_by(canonical_address, length(coalesce(canonical_address, ''))) AS sample_address
            FROM keyed
            GROUP BY cluster_key
            HAVING SUM(CASE WHEN {ofac} THEN 1 ELSE 0 END) >= 1
               AND SUM(CASE WHEN {cot} THEN 1 ELSE 0 END) >= 1
        )
        SELECT * FROM base
        ORDER BY
            (charity_n > 0)::INT + (grant_n > 0)::INT + (dot_n > 0)::INT
              + (fec_n > 0)::INT + (medicare_n > 0)::INT + (contractor_n > 0)::INT DESC,
            ofac_entities DESC,
            cotenant_n DESC,
            multi_type_count DESC,
            total_rows DESC
        LIMIT ?
        """
        fetch_limit = max_clusters * 10
    elif slice_by == "address":
        sql = f"""
        WITH ofac_keys AS (
            SELECT DISTINCT a.canonical_address AS cluster_key
            FROM Addresses a
            WHERE a.address_type = 'ofac_sanction'
              AND a.canonical_address IS NOT NULL
              AND {_STREET_QUALITY_SQL.replace('canonical_address', 'a.canonical_address')}
              AND {_US_FOOTPRINT_SQL_A}
        ),
        keyed AS (
            SELECT
                a.canonical_address AS cluster_key,
                a.address_type AS address_type,
                a.owner_id AS owner_id,
                a.canonical_address AS canonical_address
            FROM Addresses a
            INNER JOIN ofac_keys k ON k.cluster_key = a.canonical_address
        ),
        base AS (
            SELECT
                cluster_key,
                COUNT(*)::BIGINT AS total_rows,
                COUNT(DISTINCT address_type)::BIGINT AS multi_type_count,
                LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
                SUM(CASE WHEN {ofac} THEN 1 ELSE 0 END)::BIGINT AS ofac_n,
                COUNT(DISTINCT CASE WHEN {ofac} THEN owner_id END)::BIGINT AS ofac_entities,
                SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_n,
                SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_n,
                SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_n,
                SUM(CASE WHEN address_type = 'contractor' THEN 1 ELSE 0 END)::BIGINT AS contractor_n,
                SUM(CASE WHEN address_type IN ('dot_carrier_phy','dot_carrier_mail')
                         THEN 1 ELSE 0 END)::BIGINT AS dot_n,
                SUM(CASE WHEN address_type LIKE 'fec%' THEN 1 ELSE 0 END)::BIGINT AS fec_n,
                SUM(CASE WHEN address_type IN ('nppes_practice','nppes_mailing')
                         THEN 1 ELSE 0 END)::BIGINT AS medicare_n,
                SUM(CASE WHEN {cot} THEN 1 ELSE 0 END)::BIGINT AS cotenant_n,
                ANY_VALUE(canonical_address) AS sample_address
            FROM keyed
            GROUP BY cluster_key
            HAVING SUM(CASE WHEN {ofac} THEN 1 ELSE 0 END) >= 1
               AND SUM(CASE WHEN {cot} THEN 1 ELSE 0 END) >= 1
        )
        SELECT * FROM base
        ORDER BY ofac_entities DESC, cotenant_n DESC, total_rows DESC
        LIMIT ?
        """
        fetch_limit = max_clusters
    elif slice_by == "zipcode":
        sql = f"""
        WITH ofac_keys AS (
            SELECT DISTINCT a.zip_code AS cluster_key
            FROM Addresses a
            INNER JOIN Zips z ON z.zip = a.zip_code
            WHERE a.address_type = 'ofac_sanction'
              AND a.zip_code IS NOT NULL AND a.zip_code != ''
        ),
        keyed AS (
            SELECT
                a.zip_code AS cluster_key,
                a.address_type AS address_type,
                a.owner_id AS owner_id,
                a.canonical_address AS canonical_address
            FROM Addresses a
            INNER JOIN ofac_keys k ON k.cluster_key = a.zip_code
        ),
        base AS (
            SELECT
                cluster_key,
                COUNT(*)::BIGINT AS total_rows,
                COUNT(DISTINCT address_type)::BIGINT AS multi_type_count,
                LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
                SUM(CASE WHEN {ofac} THEN 1 ELSE 0 END)::BIGINT AS ofac_n,
                COUNT(DISTINCT CASE WHEN {ofac} THEN owner_id END)::BIGINT AS ofac_entities,
                SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_n,
                SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_n,
                SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_n,
                SUM(CASE WHEN address_type = 'contractor' THEN 1 ELSE 0 END)::BIGINT AS contractor_n,
                SUM(CASE WHEN address_type IN ('dot_carrier_phy','dot_carrier_mail')
                         THEN 1 ELSE 0 END)::BIGINT AS dot_n,
                SUM(CASE WHEN address_type LIKE 'fec%' THEN 1 ELSE 0 END)::BIGINT AS fec_n,
                SUM(CASE WHEN address_type IN ('nppes_practice','nppes_mailing')
                         THEN 1 ELSE 0 END)::BIGINT AS medicare_n,
                SUM(CASE WHEN {cot} THEN 1 ELSE 0 END)::BIGINT AS cotenant_n,
                max_by(canonical_address, length(coalesce(canonical_address, ''))) AS sample_address
            FROM keyed
            GROUP BY cluster_key
            HAVING SUM(CASE WHEN {ofac} THEN 1 ELSE 0 END) >= 1
               AND SUM(CASE WHEN {cot} THEN 1 ELSE 0 END) >= 1
        )
        SELECT * FROM base
        ORDER BY ofac_entities DESC, cotenant_n DESC, total_rows DESC
        LIMIT ?
        """
        fetch_limit = max_clusters
    elif slice_by == "loose_colocator":
        # Half-degree grid (~55km) — neighborhood widen between tight LL and ZIP.
        loose = effective_loose_colocator_expr("a", "g")
        key_ok = f"""
          ({loose}) IS NOT NULL
          AND TRIM(CAST(({loose}) AS VARCHAR)) != ''
          AND ({loose}) LIKE 'LL:%'
        """
        sql = f"""
        WITH ofac_keys AS (
            SELECT DISTINCT ({loose}) AS cluster_key
            FROM Addresses a
            LEFT JOIN Geocoding g ON g.geocoding_id = a.geocoding_id
            WHERE a.address_type = 'ofac_sanction'
              AND {key_ok}
              AND {_US_FOOTPRINT_SQL_A}
        ),
        keyed AS (
            SELECT
                ({loose}) AS cluster_key,
                a.address_type AS address_type,
                a.owner_id AS owner_id,
                a.canonical_address AS canonical_address
            FROM Addresses a
            LEFT JOIN Geocoding g ON g.geocoding_id = a.geocoding_id
            INNER JOIN ofac_keys k ON k.cluster_key = ({loose})
            WHERE {key_ok}
        ),
        base AS (
            SELECT
                cluster_key,
                COUNT(*)::BIGINT AS total_rows,
                COUNT(DISTINCT address_type)::BIGINT AS multi_type_count,
                LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
                SUM(CASE WHEN {ofac} THEN 1 ELSE 0 END)::BIGINT AS ofac_n,
                COUNT(DISTINCT CASE WHEN {ofac} THEN owner_id END)::BIGINT AS ofac_entities,
                SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_n,
                SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_n,
                SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_n,
                SUM(CASE WHEN address_type = 'contractor' THEN 1 ELSE 0 END)::BIGINT AS contractor_n,
                SUM(CASE WHEN address_type IN ('dot_carrier_phy','dot_carrier_mail')
                         THEN 1 ELSE 0 END)::BIGINT AS dot_n,
                SUM(CASE WHEN address_type LIKE 'fec%' THEN 1 ELSE 0 END)::BIGINT AS fec_n,
                SUM(CASE WHEN address_type IN ('nppes_practice','nppes_mailing')
                         THEN 1 ELSE 0 END)::BIGINT AS medicare_n,
                SUM(CASE WHEN {cot} THEN 1 ELSE 0 END)::BIGINT AS cotenant_n,
                max_by(canonical_address, length(coalesce(canonical_address, ''))) AS sample_address
            FROM keyed
            GROUP BY cluster_key
            HAVING SUM(CASE WHEN {ofac} THEN 1 ELSE 0 END) >= 1
               AND SUM(CASE WHEN {cot} THEN 1 ELSE 0 END) >= 1
        )
        SELECT * FROM base
        ORDER BY
            ofac_entities DESC,
            cotenant_n DESC,
            multi_type_count DESC,
            total_rows DESC
        LIMIT ?
        """
        fetch_limit = max_clusters * 5
    else:
        raise ValueError(f"Unknown slice_by={slice_by!r}")

    rows = con.execute(sql, [fetch_limit]).fetchall()
    cols = [
        "cluster_key", "total_rows", "multi_type_count", "address_types",
        "ofac_n", "ofac_entities", "charity_n", "grant_n", "officer_n",
        "contractor_n", "dot_n", "fec_n", "medicare_n", "cotenant_n",
        "sample_address",
    ]
    out = []
    for row in rows:
        c = dict(zip(cols, row))
        if isinstance(c["address_types"], str):
            c["address_types"] = [
                t.strip() for t in c["address_types"].strip("[]").split(",") if t.strip()
            ]
        elif c["address_types"] is None:
            c["address_types"] = []
        else:
            c["address_types"] = list(c["address_types"])
        if slice_by == "colocator":
            if not is_quality_colocator_key(str(c["cluster_key"])):
                continue
            # Prefer US street sample; drop foreign shells (London, Phnom Penh, …)
            if not is_us_street_address(c.get("sample_address")):
                continue
        elif slice_by == "loose_colocator":
            if not is_quality_loose_key(str(c["cluster_key"])):
                continue
            # Grid is widen — still prefer a US sample street when present
            if c.get("sample_address") and not is_us_street_address(c.get("sample_address")):
                # Allow if only foreign samples in cell but key is US lat/lon grid
                pass
        elif slice_by == "address":
            # Exact string must be US street (not Monomark House London, etc.)
            if not is_us_street_address(str(c["cluster_key"])):
                continue
            c["sample_address"] = str(c["cluster_key"])
        # Catalog score (not "severity"): more SDN entities / rows first, then co-tenants.
        # OFAC hits are not ranked by moral weight — all list membership is equally serious.
        c["score"] = (
            int(c["ofac_entities"] or 0) * 1000
            + int(c["ofac_n"] or 0) * 10
            + int(c["cotenant_n"] or 0)
        )
        c["slice_by"] = slice_by
        out.append(c)
        if len(out) >= max_clusters:
            break
    return out


def _member_from(slice_by: str) -> tuple[str, str, str]:
    """(key_expr, where_extra, from_join) for Addresses alias a."""
    if slice_by == "colocator":
        colo = effective_colocator_expr("a", "g")
        return (
            colo,
            (
                f"({colo}) IS NOT NULL AND ({colo}) NOT LIKE 'FA:%' "
                f"AND ({colo}) NOT LIKE 'grok:%' AND ({colo}) NOT LIKE 'PARTIAL:%' "
                f"AND ({colo}) NOT LIKE 'BOGUS:%' AND ({colo}) NOT LIKE '%{{zip}}%' "
                f"AND ({colo}) NOT ILIKE '%UNKN%' AND ({colo}) NOT ILIKE '%VAGUE%'"
            ),
            "LEFT JOIN Geocoding g ON g.geocoding_id = a.geocoding_id",
        )
    if slice_by == "loose_colocator":
        loose = effective_loose_colocator_expr("a", "g")
        return (
            loose,
            f"({loose}) IS NOT NULL AND ({loose}) LIKE 'LL:%'",
            "LEFT JOIN Geocoding g ON g.geocoding_id = a.geocoding_id",
        )
    if slice_by == "address":
        return (
            "a.canonical_address",
            (
                "a.canonical_address IS NOT NULL AND TRIM(a.canonical_address) != '' "
                "AND LENGTH(TRIM(a.canonical_address)) >= 12 "
                "AND a.canonical_address LIKE '%,%' "
                "AND regexp_matches(a.canonical_address, '[0-9]')"
            ),
            "",
        )
    if slice_by == "zipcode":
        return (
            "a.zip_code",
            "a.zip_code IS NOT NULL AND a.zip_code != ''",
            "INNER JOIN Zips z ON z.zip = a.zip_code",
        )
    raise ValueError(slice_by)


def fetch_ofac_entities(
    con: duckdb.DuckDBPyConnection, slice_by: str, cluster_key: str, top_n: int = 100
) -> list[dict[str, Any]]:
    key, where, j = _member_from(slice_by)
    # Avoid double-joining Geocoding when colocator path already uses alias g
    if "Geocoding g " in j or "Geocoding g\n" in j:
        colo_sel = "COALESCE(NULLIF(TRIM(a.colocator),''), NULLIF(TRIM(g.colocator),''))"
        extra_geo = ""
    else:
        colo_sel = "COALESCE(NULLIF(TRIM(a.colocator),''), NULLIF(TRIM(gx.colocator),''))"
        extra_geo = "LEFT JOIN Geocoding gx ON gx.geocoding_id = a.geocoding_id"
    rows = con.execute(
        f"""
        SELECT
            e.ofac_uid,
            e.primary_name,
            e.entity_type,
            e.entity_subtype,
            e.list_type,
            e.list_date,
            e.source_issue_date,
            a.canonical_address,
            a.city, a.state, a.zip_code,
            {colo_sel} AS colo,
            (
                SELECT STRING_AGG(DISTINCT p.program_code, ', ' ORDER BY p.program_code)
                FROM sanctioned_programs p WHERE p.entity_id = e.id
            ) AS programs,
            (
                SELECT STRING_AGG(x.name, ' | ' ORDER BY x.name)
                FROM (
                    SELECT n.name
                    FROM sanctioned_names n
                    WHERE n.entity_id = e.id
                      AND COALESCE(n.low_quality, FALSE) = FALSE
                    ORDER BY n.is_primary DESC, n.name
                    LIMIT 8
                ) x
            ) AS aliases,
            (
                SELECT STRING_AGG(i.id_type || '=' || i.id_number, ' | '
                                  ORDER BY CASE WHEN i.id_type = 'US FEIN' THEN 0 ELSE 1 END, i.id_number)
                FROM sanctioned_identifiers i
                WHERE i.entity_id = e.id
                  AND i.id_type IN ('US FEIN', 'Tax ID No.')
            ) AS tax_ids_raw,
            (
                SELECT regexp_replace(i.id_number, '[^0-9]', '', 'g')
                FROM sanctioned_identifiers i
                WHERE i.entity_id = e.id
                  AND i.id_type IN ('US FEIN', 'Tax ID No.')
                  AND length(regexp_replace(i.id_number, '[^0-9]', '', 'g')) = 9
                ORDER BY CASE WHEN i.id_type = 'US FEIN' THEN 0 ELSE 1 END
                LIMIT 1
            ) AS ein9,
            (
                SELECT i.id_type
                FROM sanctioned_identifiers i
                WHERE i.entity_id = e.id
                  AND i.id_type IN ('US FEIN', 'Tax ID No.')
                  AND length(regexp_replace(i.id_number, '[^0-9]', '', 'g')) = 9
                ORDER BY CASE WHEN i.id_type = 'US FEIN' THEN 0 ELSE 1 END
                LIMIT 1
            ) AS ein_id_type
        FROM Addresses a
        {j}
        {extra_geo}
        JOIN sanctioned_entities e ON e.id = a.owner_id
        WHERE ({key}) = ?
          AND ({where})
          AND a.address_type = 'ofac_sanction'
        ORDER BY e.primary_name
        LIMIT ?
        """,
        [cluster_key, top_n],
    ).fetchall()
    cols = [
        "ofac_uid", "primary_name", "entity_type", "entity_subtype", "list_type",
        "list_date", "source_issue_date", "canonical_address", "city", "state",
        "zip_code", "colo", "programs", "aliases", "tax_ids_raw", "ein9", "ein_id_type",
    ]
    out = [dict(zip(cols, r)) for r in rows]
    for e in out:
        e["ein9"] = normalize_ein9(e.get("ein9"))
        e["ein_fmt"] = fmt_ein(e.get("ein9"))
        e["charity_match"] = None
        e["charity_match_name"] = None
        e["charity_match_receipts"] = None
    return out


def enrich_ofac_with_990(
    con: duckdb.DuckDBPyConnection, ofac: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join OFAC US FEIN / Tax ID to Charities (filer) and BMF (registry)."""
    eins = sorted({e["ein9"] for e in ofac if e.get("ein9")})
    if not eins:
        return ofac
    by_ein: dict[str, dict[str, Any]] = {}
    rows = con.execute(
        """
        SELECT
            regexp_replace(c.ein, '[^0-9]', '', 'g') AS ein9,
            c.ein AS ein_raw,
            c.filer_name,
            c.tax_year,
            c.receipt_amt,
            c.grift_ratio
        FROM Charities c
        WHERE regexp_replace(c.ein, '[^0-9]', '', 'g') IN (SELECT UNNEST(?::VARCHAR[]))
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY regexp_replace(c.ein, '[^0-9]', '', 'g')
            ORDER BY c.tax_year DESC NULLS LAST, c.receipt_amt DESC NULLS LAST
        ) = 1
        """,
        [eins],
    ).fetchall()
    for ein9, ein_raw, name, year, receipt, grift in rows:
        if not ein9:
            continue
        by_ein[str(ein9)] = {
            "source": "charity",
            "ein": ein_raw or fmt_ein(ein9),
            "filer_name": name,
            "tax_year": year,
            "receipt_amt": receipt,
            "receipt_fmt": fmt_money(receipt),
            "grift_ratio": grift,
        }
    # BMF for EINs not on a 990 filer
    missing = [e for e in eins if e not in by_ein]
    if missing:
        try:
            b_rows = con.execute(
                """
                SELECT
                    regexp_replace(b.EIN, '[^0-9]', '', 'g') AS ein9,
                    b.EIN, b.NAME, b.STREET, b.CITY, b.STATE, b.ZIP,
                    b.SUBSECTION, b.RULING, b.FOUNDATION, b.group_code
                FROM BMF b
                WHERE regexp_replace(b.EIN, '[^0-9]', '', 'g')
                      IN (SELECT UNNEST(?::VARCHAR[]))
                """,
                [missing],
            ).fetchall()
            for r in b_rows:
                ein9 = str(r[0] or "")
                if not ein9 or ein9 in by_ein:
                    continue
                by_ein[ein9] = {
                    "source": "bmf",
                    "ein": r[1] or fmt_ein(ein9),
                    "filer_name": r[2],
                    "street": r[3],
                    "city": r[4],
                    "state": r[5],
                    "zip": r[6],
                    "subsection": r[7],
                    "ruling": r[8],
                    "foundation": r[9],
                    "group_code": r[10],
                    "tax_year": None,
                    "receipt_fmt": None,
                    "grift_ratio": None,
                }
        except Exception as ex:
            print(f"  BMF lookup note: {ex}", flush=True)
    for e in ofac:
        m = by_ein.get(e.get("ein9") or "")
        e["is_filer"] = bool(m and m.get("source") == "charity")
        e["is_bmf_only"] = bool(m and m.get("source") == "bmf")
        if m:
            e["charity_match"] = m
            e["charity_match_name"] = m.get("filer_name")
            e["charity_match_receipts"] = m.get("receipt_fmt")
            e["match_source"] = m.get("source")
        else:
            e["match_source"] = None
    return ofac


def render_ein_detail(
    *,
    ein9: str,
    bmf: dict[str, Any] | None,
    ofac_refs: list[dict[str, Any]],
    generated_at: str,
) -> str:
    """Static page for BMF-only EINs (no 990 filer → no sankey)."""
    name = (bmf or {}).get("filer_name") or (bmf or {}).get("NAME") or "Unknown"
    addr_parts = [
        (bmf or {}).get("street") or (bmf or {}).get("STREET"),
        (bmf or {}).get("city") or (bmf or {}).get("CITY"),
        (bmf or {}).get("state") or (bmf or {}).get("STATE"),
        (bmf or {}).get("zip") or (bmf or {}).get("ZIP"),
    ]
    addr = ", ".join(str(p) for p in addr_parts if p)
    ofac_rows = [
        [
            f'<code>{esc(o.get("ofac_uid"))}</code>',
            f'<strong>{esc(o.get("primary_name"))}</strong>',
            esc(o.get("list_type")),
            esc(o.get("programs")),
        ]
        for o in ofac_refs
    ]
    ofac_tbl = table_html(
        ["OFAC UID", "Primary name", "List", "Programs"], ofac_rows
    ) if ofac_rows else "<p class='meta'>No SDN rows linked in this package run.</p>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>EIN {esc(fmt_ein(ein9))} — BMF</title>
  <style>{CSS}</style>
</head>
<body>
{banner_html()}
{crumbs([
    ("OFAC reports", "../index.html"),
    ("EIN detail", None),
])}
<header>
  <h1>EIN {esc(fmt_ein(ein9))}</h1>
  <p class="meta">BMF registry only — no Form 990 filer in this database.
    Generated {esc(generated_at)}</p>
</header>
<section class="cards">
  <div class="card"><strong>{esc(fmt_ein(ein9))}</strong><span>EIN</span></div>
  <div class="card"><strong>BMF</strong><span>source</span></div>
</section>
<section class="section">
  <h2>IRS BMF</h2>
  <table>
    <tr><th>Name</th><td>{esc(name)}</td></tr>
    <tr><th>Address</th><td>{esc(addr) or "—"}</td></tr>
    <tr><th>Subsection</th><td>{esc((bmf or {}).get("subsection") or (bmf or {}).get("SUBSECTION"))}</td></tr>
    <tr><th>Ruling</th><td>{esc((bmf or {}).get("ruling") or (bmf or {}).get("RULING"))}</td></tr>
    <tr><th>Foundation</th><td>{esc((bmf or {}).get("foundation") or (bmf or {}).get("FOUNDATION"))}</td></tr>
    <tr><th>Group code</th><td>{esc((bmf or {}).get("group_code"))}</td></tr>
  </table>
</section>
<section class="section">
  <h2>Linked OFAC / SDN (this package)</h2>
  {ofac_tbl}
</section>
<footer>
{COLOCATION_DISCLAIMER_HTML}
  <p class="disclaimer">BMF is the IRS exempt-organization master file. Absence of a 990
    filing in this DB does not mean the org never filed; coverage depends on ingest years.</p>
  <p><a href="../index.html">← OFAC reports</a></p>
</footer>
</body>
</html>
"""


def fetch_charities(con, slice_by, key, top_n=40) -> list[dict]:
    k, w, j = _member_from(slice_by)
    rows = con.execute(
        f"""
        SELECT DISTINCT c.ein, c.filer_name, c.tax_year, c.receipt_amt, c.grift_ratio
        FROM Addresses a
        {j}
        JOIN Charities c ON c.charity_id = a.owner_id
        WHERE ({k}) = ? AND ({w}) AND a.address_type = 'charity'
        ORDER BY c.receipt_amt DESC NULLS LAST
        LIMIT ?
        """,
        [key, top_n],
    ).fetchall()
    return [
        {
            "ein": r[0], "filer_name": r[1], "tax_year": r[2],
            "receipt_amt": r[3], "receipt_fmt": fmt_money(r[3]), "grift_ratio": r[4],
        }
        for r in rows
    ]


def fetch_grants(con, slice_by, key, top_n=40) -> list[dict]:
    k, w, j = _member_from(slice_by)
    rows = con.execute(
        f"""
        SELECT DISTINCT gr.filer_ein, gr.grantee_name, gr.grant_amt, gr.tax_year
        FROM Addresses a
        {j}
        JOIN Grants gr ON gr.grant_id = a.owner_id
        WHERE ({k}) = ? AND ({w}) AND a.address_type = 'grant'
        ORDER BY gr.grant_amt DESC NULLS LAST
        LIMIT ?
        """,
        [key, top_n],
    ).fetchall()
    return [
        {
            "filer_ein": r[0], "grantee_name": r[1], "grant_amt": r[2],
            "amt_fmt": fmt_money(r[2]), "tax_year": r[3],
        }
        for r in rows
    ]


def fetch_dot(con, slice_by, key, top_n=50) -> list[dict]:
    k, w, j = _member_from(slice_by)
    rows = con.execute(
        f"""
        SELECT DISTINCT d.dot_number, d.legal_name, d.dba_name, d.status_code,
               d.power_units, d.phone, a.canonical_address
        FROM Addresses a
        {j}
        JOIN dot_carriers d ON d.id = a.owner_id
        WHERE ({k}) = ? AND ({w})
          AND a.address_type IN ('dot_carrier_phy','dot_carrier_mail')
        ORDER BY d.power_units DESC NULLS LAST
        LIMIT ?
        """,
        [key, top_n],
    ).fetchall()
    return [
        {
            "dot_number": r[0], "legal_name": r[1], "dba_name": r[2],
            "status_code": r[3], "power_units": r[4], "phone": r[5],
            "canonical_address": r[6],
        }
        for r in rows
    ]


def fetch_fec_summary(con, slice_by, key) -> dict[str, int]:
    k, w, j = _member_from(slice_by)
    row = con.execute(
        f"""
        SELECT
          SUM(CASE WHEN a.address_type = 'fec_contributor' THEN 1 ELSE 0 END),
          SUM(CASE WHEN a.address_type = 'fec_committee' THEN 1 ELSE 0 END),
          SUM(CASE WHEN a.address_type = 'fec_committee_transaction' THEN 1 ELSE 0 END),
          SUM(CASE WHEN a.address_type = 'fec_operating_expenditure' THEN 1 ELSE 0 END),
          SUM(CASE WHEN a.address_type = 'fec_candidate_spending' THEN 1 ELSE 0 END)
        FROM Addresses a
        {j}
        WHERE ({k}) = ? AND ({w}) AND a.address_type LIKE 'fec%'
        """,
        [key],
    ).fetchone()
    return {
        "fec_contributor": int(row[0] or 0),
        "fec_committee": int(row[1] or 0),
        "fec_committee_transaction": int(row[2] or 0),
        "fec_operating_expenditure": int(row[3] or 0),
        "fec_candidate_spending": int(row[4] or 0),
    }


def fetch_sub_addresses(con, slice_by, key, top_n=40) -> list[dict]:
    if slice_by == "address":
        return []
    k, w, j = _member_from(slice_by)
    rows = con.execute(
        f"""
        SELECT
            COALESCE(NULLIF(TRIM(a.canonical_address), ''), '(no street)') AS addr,
            COUNT(*)::BIGINT AS n,
            COUNT(DISTINCT a.address_type)::BIGINT AS multi,
            SUM(CASE WHEN a.address_type = 'ofac_sanction' THEN 1 ELSE 0 END)::BIGINT AS ofac_n,
            LIST(DISTINCT a.address_type ORDER BY a.address_type) AS types
        FROM Addresses a
        {j}
        WHERE ({k}) = ? AND ({w})
        GROUP BY 1
        ORDER BY ofac_n DESC, n DESC
        LIMIT ?
        """,
        [key, top_n],
    ).fetchall()
    out = []
    for addr, n, multi, ofac_n, types in rows:
        if isinstance(types, str):
            tl = [t.strip() for t in types.strip("[]").split(",") if t.strip()]
        else:
            tl = list(types or [])
        out.append({
            "canonical_address": addr,
            "total_rows": int(n or 0),
            "multi_type_count": int(multi or 0),
            "ofac_n": int(ofac_n or 0),
            "address_types": tl,
            "maps_url": maps_url(addr) if addr and not str(addr).startswith("(") else "",
        })
    return out


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

# Shared disclaimer — co-location is a lead, not guilt by address.
COLOCATION_DISCLAIMER_SHORT = (
    "Shared address is a lead, not a finding. Co-tenants are not presumed to share "
    "the SDN's conduct—only the footprint."
)

COLOCATION_DISCLAIMER_HTML = """
  <p class="disclaimer">
    <strong>Do not assume.</strong> Co-location means a shared street / building / ZIP key
    in the data—not control, ownership, conspiracy, or the same conduct.
    Jeffrey Dahmer was a cannibal; his neighbors were not cannibals—just neighbors.
    My father-in-law lived in a bordello; he was not a whore—he was a teenage runaway
    hiding from his stepfather until he could join the Air Force.
    <em>Same footprint ≠ same role.</em>
  </p>
  <p class="disclaimer">
    Analytic research product (not an official OFAC product). OFAC UID / primary names
    come from Treasury SDN advanced XML. Co-tenants join from IRS Form 990, FMCSA DOT,
    FEC, and CMS NPPES/Medicare <strong>only by shared address keys</strong>
    (or noted EIN joins)—not by name match unless stated. Confirm UIDs on
    <a href="https://sanctionssearch.ofac.treas.gov/" target="_blank" rel="noopener">sanctionssearch.ofac.treas.gov</a>.
  </p>
"""


def banner_html() -> str:
    return """
<div class="banner">
  <strong>OFAC SDN co-location package</strong> —
  Locations where a Treasury OFAC Specially Designated National (or consolidated-list)
  entity shares a street / building / ZIP footprint with IRS Form 990 organizations,
  DOT motor carriers, FEC political money, or Medicare providers.
  <br>Source list: Treasury OFAC advanced SDN XML (ingested into local research DB).
  This is an analytic package, not an official OFAC product.
  <br><strong>Do not assume:</strong> Dahmer’s neighbors were not cannibals—just neighbors.
  My father-in-law lived in a bordello; he was not a whore—just a teenage runaway
  waiting to join the Air Force. Shared address is a lead, not guilt.
  <br><strong>Ranking:</strong> this is a <em>catalog</em> of co-locations (by SDN entity
  count / footprint size), not a league table of “how bad.” Prefer
  <strong>colocator</strong> then <strong>loose colocator</strong>; exact-address match
  is rare (suite spelling).
</div>
"""
# (banner intentionally has no third-party site names)


SLICE_LABELS = {
    "colocator": "Colocator (building / PO)",
    "loose_colocator": "Loose colocator (0.5° grid)",
    "address": "Exact address",
    "zipcode": "ZIP code (widen)",
}


def crumbs(parts: list[tuple[str, str | None]]) -> str:
    """Breadcrumb trail. href=None → current page (non-link)."""
    bits = []
    for label, href in parts:
        if href:
            bits.append(f'<a href="{esc(href)}">{esc(label)}</a>')
        else:
            bits.append(f'<span class="bc-current">{esc(label)}</span>')
    sep = ' <span class="bc-sep">›</span> '
    return f'<nav class="crumbs" aria-label="Breadcrumb">{sep.join(bits)}</nav>'


def table_html(headers: list[str], rows: list[list[Any]], *, row_class: list[str] | None = None) -> str:
    if not rows:
        return "<p class=\"meta\">None in top-N for this cluster.</p>"
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for i, r in enumerate(rows):
        cls = ""
        if row_class and i < len(row_class) and row_class[i]:
            cls = f' class="{row_class[i]}"'
        tds = "".join(f"<td>{c}</td>" for c in r)  # pre-escaped or trusted HTML
        body.append(f"<tr{cls}>{tds}</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


# TanStack Table (CDN) — sort / search / pagination for index pages
TANSTACK_CSS = """
  .ts-wrap { margin: 0.5rem 0 1rem; }
  .ts-toolbar {
    display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center;
    margin-bottom: 0.5rem; font-size: 0.9rem;
  }
  .ts-toolbar input[type="search"] {
    min-width: 200px; padding: 0.35rem 0.55rem; border: 1px solid #ccc; border-radius: 4px;
  }
  .ts-toolbar select { padding: 0.3rem 0.4rem; }
  .ts-pager { display: flex; gap: 0.4rem; align-items: center; margin-left: auto; }
  .ts-pager button {
    padding: 0.25rem 0.55rem; border: 1px solid #ccc; background: #fff;
    border-radius: 4px; cursor: pointer;
  }
  .ts-pager button:disabled { opacity: 0.4; cursor: default; }
  #ts-table-root table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
  #ts-table-root th, #ts-table-root td {
    border: 1px solid #ddd; padding: 0.45rem 0.55rem; text-align: left; vertical-align: top;
  }
  #ts-table-root th {
    background: #f4f4f4; position: sticky; top: 0; cursor: pointer; user-select: none;
    white-space: nowrap;
  }
  #ts-table-root th .sort-ind { color: #888; font-size: 0.75rem; margin-left: 0.25rem; }
  #ts-table-root th.sorted { background: #e8f0fe; }
  #ts-table-root tr:nth-child(even) { background: #fafafa; }
  #ts-table-root tr.ofac-row { background: #fef2f2 !important; }
  .ts-meta { font-size: 0.85rem; color: #666; }
  .ts-empty { color: #888; font-size: 0.9rem; padding: 0.5rem 0; }
"""

TANSTACK_BOOT = r"""
<script type="module">
import {
  createTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
} from "https://cdn.jsdelivr.net/npm/@tanstack/table-core@8.20.5/+esm";

function num(v) {
  if (v == null || v === "" || v === "—") return null;
  if (typeof v === "number") return v;
  const n = Number(String(v).replace(/[$,]/g, ""));
  return Number.isFinite(n) ? n : null;
}
function cmp(a, b) {
  const na = num(a), nb = num(b);
  if (na != null && nb != null) return na === nb ? 0 : na < nb ? -1 : 1;
  const sa = (a == null ? "" : String(a)).toLowerCase();
  const sb = (b == null ? "" : String(b)).toLowerCase();
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function renderCellHtml(colId, row, raw) {
  if (colId.endsWith("_html") && raw != null) return String(raw);
  const htmlKey = colId + "_html";
  if (row[htmlKey] != null) return row[htmlKey];
  if (raw == null || raw === "") return "—";
  return escapeHtml(String(raw));
}

function mountTanStackTable(root, cfg) {
  if (!root || !cfg || !cfg.rows || !cfg.columns) return;
  if (!cfg.rows.length) {
    root.innerHTML = '<p class="ts-empty">No rows</p>';
    return;
  }
  let sorting = Array.isArray(cfg.initialSort) ? cfg.initialSort.slice() : [];
  let globalFilter = "";
  let pagination = { pageIndex: 0, pageSize: cfg.pageSize || 25 };
  const columns = cfg.columns.map((c) => ({
    id: c.id,
    accessorKey: c.id,
    header: c.header,
    enableSorting: c.sortable !== false,
    cell: (info) => info.getValue(),
    sortingFn: (rowA, rowB, columnId) =>
      cmp(rowA.getValue(columnId), rowB.getValue(columnId)),
  }));

  function tableState() {
    return {
      sorting, globalFilter, pagination,
      columnFilters: [], columnVisibility: {}, columnOrder: [],
      columnPinning: { left: [], right: [] },
      rowPinning: { top: [], bottom: [] },
      columnSizing: {},
      columnSizingInfo: {
        startOffset: null, startSize: null, deltaOffset: null,
        deltaPercentage: null, isResizingColumn: false, columnSizingStart: [],
      },
      rowSelection: {}, expanded: {}, grouping: [],
    };
  }

  function makeTable() {
    return createTable({
      data: cfg.rows,
      columns,
      state: tableState(),
      onSortingChange: (u) => { sorting = typeof u === "function" ? u(sorting) : u; redraw(); },
      onGlobalFilterChange: (u) => {
        globalFilter = typeof u === "function" ? u(globalFilter) : u;
        pagination = { ...pagination, pageIndex: 0 };
        redraw();
      },
      onPaginationChange: (u) => {
        pagination = typeof u === "function" ? u(pagination) : u;
        redraw();
      },
      getCoreRowModel: getCoreRowModel(),
      getSortedRowModel: getSortedRowModel(),
      getFilteredRowModel: getFilteredRowModel(),
      getPaginationRowModel: getPaginationRowModel(),
      globalFilterFn: (row, _cid, filterValue) => {
        if (!filterValue) return true;
        const q = String(filterValue).toLowerCase();
        return Object.keys(row.original).some((k) => {
          if (k.endsWith("_html")) return false;
          const v = row.original[k];
          return v != null && String(v).toLowerCase().includes(q);
        });
      },
    });
  }

  function redraw() {
    const table = makeTable();
    const pageRows = table.getRowModel().rows;
    const filteredCount = table.getFilteredRowModel().rows.length;
    const sortMap = Object.fromEntries(
      (table.getState().sorting || []).map((s) => [s.id, s.desc ? "desc" : "asc"])
    );
    const leafCols = table.getAllLeafColumns();
    const headerCells = leafCols.map((col) => {
      const sorted = sortMap[col.id];
      const ind = sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "⇅";
      const cls = sorted ? "sorted" : "";
      return `<th class="${cls}" data-col="${escapeHtml(col.id)}">${escapeHtml(String(col.columnDef.header))}<span class="sort-ind">${ind}</span></th>`;
    }).join("");
    const body = pageRows.map((r) => {
      const o = r.original;
      const trCls = o.row_class || "";
      const tds = leafCols.map((col) =>
        `<td>${renderCellHtml(col.id, o, o[col.id])}</td>`
      ).join("");
      return `<tr class="${trCls}">${tds}</tr>`;
    }).join("");
    const pageCount = Math.max(1, Math.ceil(filteredCount / pagination.pageSize) || 1);
    const pageIndex = pagination.pageIndex;
    const sizes = cfg.pageSizeOptions || [10, 25, 50, 100, 200];
    root.innerHTML = `
      <div class="ts-wrap">
        <div class="ts-toolbar">
          <label>Search <input type="search" class="ts-search" placeholder="Filter rows…" value="${escapeHtml(globalFilter)}"></label>
          <label>Page size
            <select class="ts-page-size">
              ${sizes.map((n) => `<option value="${n}" ${n === pagination.pageSize ? "selected" : ""}>${n}</option>`).join("")}
            </select>
          </label>
          <span class="ts-meta">${filteredCount} rows · page ${pageIndex + 1}/${pageCount}</span>
          <div class="ts-pager">
            <button type="button" class="ts-first" ${pageIndex <= 0 ? "disabled" : ""}>«</button>
            <button type="button" class="ts-prev" ${pageIndex <= 0 ? "disabled" : ""}>‹</button>
            <button type="button" class="ts-next" ${pageIndex >= pageCount - 1 ? "disabled" : ""}>›</button>
            <button type="button" class="ts-last" ${pageIndex >= pageCount - 1 ? "disabled" : ""}>»</button>
          </div>
        </div>
        <table><thead><tr>${headerCells}</tr></thead><tbody>${body}</tbody></table>
      </div>`;
    root.querySelectorAll("th[data-col]").forEach((th) => {
      th.addEventListener("click", () => {
        const id = th.getAttribute("data-col");
        const cur = sorting.find((s) => s.id === id);
        if (!cur) sorting = [{ id, desc: true }];
        else if (cur.desc) sorting = [{ id, desc: false }];
        else sorting = [];
        redraw();
      });
    });
    const search = root.querySelector(".ts-search");
    search.addEventListener("input", () => {
      globalFilter = search.value;
      pagination = { ...pagination, pageIndex: 0 };
      redraw();
    });
    root.querySelector(".ts-page-size").addEventListener("change", (e) => {
      pagination = { pageIndex: 0, pageSize: Number(e.target.value) || 25 };
      redraw();
    });
    root.querySelector(".ts-first").addEventListener("click", () => {
      pagination = { ...pagination, pageIndex: 0 }; redraw();
    });
    root.querySelector(".ts-prev").addEventListener("click", () => {
      pagination = { ...pagination, pageIndex: Math.max(0, pagination.pageIndex - 1) }; redraw();
    });
    root.querySelector(".ts-next").addEventListener("click", () => {
      pagination = { ...pagination, pageIndex: pagination.pageIndex + 1 }; redraw();
    });
    root.querySelector(".ts-last").addEventListener("click", () => {
      pagination = { ...pagination, pageIndex: Math.max(0, pageCount - 1) }; redraw();
    });
  }
  redraw();
}

const cfg = window.__CLUSTER_TABLE__;
if (cfg) {
  const root = document.getElementById("ts-table-root");
  if (root) mountTanStackTable(root, cfg);
}
</script>
"""


def render_index(
    *,
    slice_by: str,
    clusters: list[dict],
    generated_at: str,
    report_date: str,
    methodology: str,
) -> str:
    labels = {
        "colocator": "Tight colocator (building / PO — FA: excluded)",
        "address": "Exact canonical street address",
        "zipcode": "Valid US ZIP (Zips catalog — widen)",
    }
    slice_nav = SLICE_LABELS.get(slice_by, slice_by)
    ts_rows = []
    for i, c in enumerate(clusters, 1):
        key = str(c["cluster_key"])
        sample = c.get("sample_address") or key
        href = c.get("detail_file") or "#"
        ts_rows.append(
            {
                "rank": i,
                "score": int(c.get("score") or 0),
                "cluster_key": key[:100],
                "cluster_key_html": (
                    f'<a href="{esc(href)}"><code>{esc(key[:80])}</code></a>'
                ),
                "sample": (sample or "")[:100],
                "ofac_entities": int(c.get("ofac_entities") or 0),
                "ofac_n": int(c.get("ofac_n") or 0),
                "ofac_with_ein": int(c.get("ofac_with_ein") or 0),
                "ein_990_match": int(c.get("ein_990_match") or 0),
                "charity_n": int(c.get("charity_n") or 0),
                "grant_n": int(c.get("grant_n") or 0),
                "dot_n": int(c.get("dot_n") or 0),
                "fec_n": int(c.get("fec_n") or 0),
                "medicare_n": int(c.get("medicare_n") or 0),
                "multi_type_count": int(c.get("multi_type_count") or 0),
                "detail": "Detail →",
                "detail_html": f'<a href="{esc(href)}">Detail →</a>',
            }
        )
    cluster_table = {
        "rows": ts_rows,
        "columns": [
            {"id": "rank", "header": "#"},
            {"id": "score", "header": "Score"},
            {"id": "cluster_key", "header": "Cluster key"},
            {"id": "sample", "header": "Sample address"},
            {"id": "ofac_entities", "header": "OFAC entities"},
            {"id": "ofac_n", "header": "OFAC rows"},
            {"id": "ofac_with_ein", "header": "With EIN/FEIN"},
            {"id": "ein_990_match", "header": "EIN→990 match"},
            {"id": "charity_n", "header": "Charity"},
            {"id": "grant_n", "header": "Grant"},
            {"id": "dot_n", "header": "DOT"},
            {"id": "fec_n", "header": "FEC"},
            {"id": "medicare_n", "header": "Medicare"},
            {"id": "multi_type_count", "header": "Types"},
            {"id": "detail", "header": ""},
        ],
        "pageSize": 50,
        "initialSort": [{"id": "score", "desc": True}],
    }
    table_json = json.dumps(cluster_table, ensure_ascii=False)

    map_html = ""
    try:
        from map_points import clusters_to_map_points  # type: ignore

        pts = clusters_to_map_points(
            [
                {
                    **c,
                    "rank_metric_value": c.get("score"),
                    "canonical_address": c.get("sample_address") or c.get("cluster_key"),
                }
                for c in clusters
            ],
            slice_by=slice_by,
            max_points=200,
        )
        if pts:
            map_html = f"""
<section class="section">
  <h2>Map (approx.)</h2>
  <p class="meta">Zip centroids / LL colocators when available. Not survey-grade.</p>
  <div id="leaflet-map" style="height:380px;border:1px solid #ddd;border-radius:8px;"></div>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    (function() {{
      const pts = {json.dumps(pts)};
      const map = L.map('leaflet-map');
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        attribution: '&copy; OpenStreetMap'
      }}).addTo(map);
      const bounds = [];
      pts.forEach(p => {{
        const m = L.circleMarker([p.lat, p.lon], {{
          radius: 7, color: '#7f1d1d', fillColor: '#dc2626', fillOpacity: 0.75
        }}).addTo(map);
        m.bindPopup(p.popup_html || p.label || '');
        bounds.push([p.lat, p.lon]);
      }});
      if (bounds.length) map.fitBounds(bounds, {{ padding: [24, 24] }});
      else map.setView([39.5, -98.35], 4);
    }})();
  </script>
</section>
"""
    except Exception as e:
        map_html = f'<p class="meta">Map unavailable: {esc(e)}</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OFAC co-location — {esc(slice_by)}</title>
  <style>{CSS}
{TANSTACK_CSS}
  </style>
</head>
<body>
{banner_html()}
{crumbs([
    ("OFAC reports", "../index.html"),
    (slice_nav, None),
])}
<header>
  <h1>OFAC co-location — {esc(labels.get(slice_by, slice_by))}</h1>
  <p class="meta">Generated {esc(generated_at)} · report day {esc(report_date)} ·
    {len(clusters):,} clusters · static HTML for offline review</p>
</header>
<div class="note">{methodology}</div>
{map_html}
<section class="section">
  <h2>Ranked clusters</h2>
  <p class="meta">Smart table (TanStack): click headers to sort, search to filter, change page size.
    Default sort = score. <strong>With EIN/FEIN</strong> = SDN has US FEIN or 9-digit Tax ID;
    <strong>EIN→990 match</strong> = that EIN appears on a Form 990 charity filer.</p>
  <div id="ts-table-root" class="ts-table-root"></div>
  <noscript><p class="meta">Enable JavaScript for sortable table. Data: <code>data/clusters.json</code></p></noscript>
</section>
<script>
  window.__CLUSTER_TABLE__ = {table_json};
</script>
{TANSTACK_BOOT}
<footer>
{COLOCATION_DISCLAIMER_HTML}
  <p class="disclaimer">
    EIN matches use <code>sanctioned_identifiers</code> (<code>US FEIN</code> / <code>Tax ID No.</code>)
    joined to <code>Charities.ein</code> when shown.
  </p>
  <p><a href="../index.html">← All OFAC suites</a></p>
</footer>
</body>
</html>
"""


def render_detail(
    *,
    cluster: dict,
    ofac: list[dict],
    charities: list[dict],
    grants: list[dict],
    dots: list[dict],
    fec: dict,
    subs: list[dict],
    generated_at: str,
    slice_by: str,
) -> str:
    key = str(cluster["cluster_key"])
    sample = cluster.get("sample_address") or key
    murl = maps_url(sample)

    ofac_rows = []
    ein_match_rows = []
    for e in ofac:
        match = e.get("charity_match") or {}
        is_filer = bool(e.get("is_filer"))
        is_bmf = bool(e.get("is_bmf_only"))
        if e.get("ein9") and is_filer:
            ein_cell = ein_link_html(e.get("ein9"), is_filer=True)
        elif e.get("ein9") and is_bmf:
            ein_cell = ein_link_html(e.get("ein9"), is_bmf=True)
        elif e.get("ein9"):
            # SDN tax ID not in Charities or BMF — business only, no link
            ein_cell = f"<code>{esc(fmt_ein(e.get('ein9')))}</code>"
        else:
            ein_cell = "—"
        match_cell = "—"
        if match and is_filer:
            match_cell = (
                f'<strong>{esc(match.get("filer_name"))}</strong> '
                f'{ein_link_html(e.get("ein9"), is_filer=True)}'
                f'<br><span class="meta">FY{esc(match.get("tax_year"))} · '
                f'{esc(match.get("receipt_fmt"))} · 990 filer · ProPublica</span>'
            )
            ein_match_rows.append([
                f'<code>{esc(e.get("ofac_uid"))}</code>',
                f'<strong>{esc(e.get("primary_name"))}</strong>',
                ein_link_html(e.get("ein9"), is_filer=True),
                esc(e.get("ein_id_type") or ""),
                "990 filer",
                esc(match.get("filer_name")),
                esc(match.get("tax_year")),
                esc(match.get("receipt_fmt")),
                esc(match.get("grift_ratio")),
            ])
        elif match and is_bmf:
            match_cell = (
                f'<strong>{esc(match.get("filer_name"))}</strong> '
                f'{ein_link_html(e.get("ein9"), is_bmf=True)}'
                f'<br><span class="meta">BMF only (no 990 filer in DB)</span>'
            )
            ein_match_rows.append([
                f'<code>{esc(e.get("ofac_uid"))}</code>',
                f'<strong>{esc(e.get("primary_name"))}</strong>',
                ein_link_html(e.get("ein9"), is_bmf=True),
                esc(e.get("ein_id_type") or ""),
                "BMF only",
                esc(match.get("filer_name")),
                "—",
                "—",
                "—",
            ])
        tax_disp = e.get("tax_ids_raw") or "—"
        ofac_rows.append([
            f'<code>{esc(e.get("ofac_uid"))}</code>',
            f'<strong>{esc(e.get("primary_name"))}</strong>',
            esc(e.get("list_type")),
            esc(e.get("entity_type")),
            ein_cell,
            esc(e.get("ein_id_type") or ""),
            esc(tax_disp)[:120],
            match_cell,
            esc(e.get("programs")),
            esc((e.get("aliases") or "")[:120]),
            esc(e.get("canonical_address") or ""),
            f'{esc(e.get("city") or "")}, {esc(e.get("state") or "")} {esc(e.get("zip_code") or "")}',
        ])
    ofac_tbl = table_html(
        [
            "OFAC UID", "Primary name", "List", "Type",
            "US EIN", "ID type", "Tax IDs (raw)", "IRS match by EIN",
            "Programs", "Aliases", "Address", "City/ST/ZIP",
        ],
        ofac_rows,
        row_class=["ofac-row"] * len(ofac_rows),
    )
    ein_match_tbl = table_html(
        [
            "OFAC UID", "SDN name", "OFAC EIN", "ID type",
            "Match kind", "IRS name", "Tax year", "Receipts", "Grift",
        ],
        ein_match_rows,
    )

    ch_tbl = table_html(
        ["EIN", "Filer", "Year", "Receipts", "Grift ratio"],
        [
            [
                ein_link_html(normalize_ein9(c.get("ein")), is_filer=True),
                esc(c.get("filer_name")),
                esc(c.get("tax_year")),
                esc(c.get("receipt_fmt")),
                esc(c.get("grift_ratio")),
            ]
            for c in charities
        ],
    )
    gr_tbl = table_html(
        ["Filer EIN", "Grantee", "Amount", "Year"],
        [
            [
                # Filer EINs on grants are 990 orgs → ProPublica
                ein_link_html(normalize_ein9(g.get("filer_ein")), is_filer=True),
                esc(g.get("grantee_name")),
                esc(g.get("amt_fmt")),
                esc(g.get("tax_year")),
            ]
            for g in grants
        ],
    )
    dot_tbl = table_html(
        ["DOT#", "Legal name", "Status", "Power units", "Phone", "Address"],
        [
            [
                dot_link_html(d.get("dot_number")),
                esc(d.get("legal_name") or d.get("dba_name")),
                esc(d.get("status_code")),
                f"{int(d.get('power_units') or 0):,}",
                esc(d.get("phone")),
                esc((d.get("canonical_address") or "")[:80]),
            ]
            for d in dots
        ],
    )
    sub_tbl = table_html(
        ["Street address", "Rows", "Types", "OFAC rows", "Map"],
        [
            [
                esc(s.get("canonical_address")),
                f"{int(s.get('total_rows') or 0):,}",
                esc(", ".join(s.get("address_types") or [])),
                f"{int(s.get('ofac_n') or 0):,}",
                (
                    f'<a href="{esc(s["maps_url"])}" target="_blank" rel="noopener">Maps</a>'
                    if s.get("maps_url")
                    else "—"
                ),
            ]
            for s in subs
        ],
    )

    chips = [
        f'<span class="chip ofac">ofac_entities={int(cluster.get("ofac_entities") or 0)}</span>',
        f'<span class="chip">types={int(cluster.get("multi_type_count") or 0)}</span>',
    ]
    for label, field in (
        ("charity", "charity_n"),
        ("grant", "grant_n"),
        ("DOT", "dot_n"),
        ("FEC", "fec_n"),
        ("Medicare", "medicare_n"),
    ):
        n = int(cluster.get(field) or 0)
        if n:
            chips.append(f'<span class="chip warn">{esc(label)}={n:,}</span>')
    for t in cluster.get("address_types") or []:
        chips.append(f'<span class="chip">{esc(t)}</span>')

    fec_line = ", ".join(f"{k}={v:,}" for k, v in fec.items() if v) or "none in top scan"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OFAC @ {esc(key[:60])}</title>
  <style>{CSS}</style>
</head>
<body>
{banner_html()}
{crumbs([
    ("OFAC reports", "../index.html"),
    (SLICE_LABELS.get(slice_by, slice_by), "index.html"),
    ((key[:48] + ("…" if len(key) > 48 else "")), None),
])}
<header>
  <h1>OFAC co-location</h1>
  <p class="meta"><code>{esc(key)}</code>
    · slice <strong>{esc(slice_by)}</strong>
    · score {int(cluster.get("score") or 0):,}
    · {esc(generated_at)}</p>
  <p><a href="{esc(murl)}" target="_blank" rel="noopener">Open sample address in Google Maps →</a>
    <span class="meta"> · e.g. {esc(sample)}</span></p>
  <div class="chips">{"".join(chips)}</div>
</header>

<section class="cards">
  <div class="card"><strong>{int(cluster.get("ofac_entities") or 0):,}</strong><span>OFAC entities</span></div>
  <div class="card"><strong>{int(cluster.get("ofac_n") or 0):,}</strong><span>OFAC address rows</span></div>
  <div class="card"><strong>{int(cluster.get("charity_n") or 0):,}</strong><span>Charity rows</span></div>
  <div class="card"><strong>{int(cluster.get("grant_n") or 0):,}</strong><span>Grant rows</span></div>
  <div class="card"><strong>{int(cluster.get("dot_n") or 0):,}</strong><span>DOT rows</span></div>
  <div class="card"><strong>{int(cluster.get("fec_n") or 0):,}</strong><span>FEC rows</span></div>
  <div class="card"><strong>{int(cluster.get("medicare_n") or 0):,}</strong><span>Medicare rows</span></div>
  <div class="card"><strong>{int(cluster.get("total_rows") or 0):,}</strong><span>Total address rows</span></div>
</section>

<section class="section">
  <h2>OFAC / SDN entities at this location</h2>
  <p class="meta">Joined via <code>Addresses.owner_id → sanctioned_entities.id</code>.
    Tax IDs from <code>sanctioned_identifiers</code> (<code>US FEIN</code>, <code>Tax ID No.</code>).
    990 match = same 9-digit EIN on <code>Charities.ein</code> (latest tax year).
    Public search: <a href="https://sanctionssearch.ofac.treas.gov/" target="_blank" rel="noopener">sanctionssearch.ofac.treas.gov</a></p>
  {ofac_tbl}
</section>

<section class="section">
  <h2>SDN tax ID → IRS EIN matches</h2>
  <p class="meta">OFAC <code>US FEIN</code> / 9-digit <code>Tax ID No.</code> matched to Charities
    (→ ProPublica Nonprofit Explorer) or BMF only (local EIN page).
    EINs not in BMF/Charities stay plain text (ordinary businesses). Not proof of control.</p>
  {ein_match_tbl if ein_match_rows else "<p class='meta'>No US FEIN / 9-digit Tax ID matched Charities or BMF for these SDN rows.</p>"}
</section>

<section class="section">
  <h2>Street-level breakdown</h2>
  {sub_tbl if subs else "<p class='meta'>Single-address cluster or no subgroups.</p>"}
</section>

<section class="section">
  <h2>IRS Form 990 charities (same address key)</h2>
  <p class="meta">Co-tenants by address — separate from EIN identity match above.</p>
  {ch_tbl}
</section>

<section class="section">
  <h2>990 grants (grantee / filer addresses)</h2>
  {gr_tbl}
</section>

<section class="section">
  <h2>DOT motor carriers</h2>
  {dot_tbl}
</section>

<section class="section">
  <h2>FEC address-row counts</h2>
  <p>{esc(fec_line)}</p>
</section>

<footer>
{COLOCATION_DISCLAIMER_HTML}
  <p>
    <a href="index.html">← {esc(SLICE_LABELS.get(slice_by, slice_by))} index</a>
    · <a href="../index.html">All OFAC suites</a>
  </p>
</footer>
</body>
</html>
"""


def render_master_index(suites: list[dict], generated_at: str) -> str:
    ts_rows = []
    for s in suites:
        href = s["href"]
        ts_rows.append(
            {
                "suite": s["label"],
                "suite_html": f'<a href="{esc(href)}"><strong>{esc(s["label"])}</strong></a>',
                "n_clusters": int(s["n_clusters"]),
                "notes": s.get("notes") or "",
                "open": "Open →",
                "open_html": f'<a href="{esc(href)}">Open →</a>',
            }
        )
    cluster_table = {
        "rows": ts_rows,
        "columns": [
            {"id": "suite", "header": "Suite"},
            {"id": "n_clusters", "header": "Clusters"},
            {"id": "notes", "header": "Notes"},
            {"id": "open", "header": ""},
        ],
        "pageSize": 25,
        "initialSort": [{"id": "n_clusters", "desc": True}],
    }
    table_json = json.dumps(cluster_table, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OFAC co-location reports</title>
  <style>{CSS}
{TANSTACK_CSS}
  </style>
</head>
<body>
{banner_html()}
{crumbs([("OFAC reports", None)])}
<header>
  <h1>OFAC SDN co-location reports</h1>
  <p class="meta">Generated {esc(generated_at)} · package: <code>ofac_reporting/</code></p>
</header>
<div class="note">
  <strong>How to read this for Treasury / enforcement triage</strong>
  <ol>
    <li><strong>Colocator</strong> — <code>LL:</code> / <code>PO:box:zip</code> (bare <code>PO:box:</code> without ZIP dropped). City shells excluded. <em>Start here</em> (e.g. same building as an SDN).</li>
    <li><strong>Loose colocator</strong> — 0.5° grid (~neighborhood). Same key as DOT/grant_match loose. Wider than building LL, tighter than ZIP.</li>
    <li><strong>Address</strong> — exact canonical string only. Often empty: suite wording rarely matches byte-for-byte. Not the primary OFAC view.</li>
    <li><strong>ZIP</strong> — valid US ZIP (widen; noisier). Context only.</li>
  </ol>
  <p class="meta">OFAC suites are a co-location <strong>catalog</strong>, not ranked by severity.
    List membership is binary; table order is footprint size / entity count for browsing.</p>
  Detail pages: SDN name, UID, programs, tax IDs (linked only if in Charities → ProPublica
  or BMF → local page), co-tenants, DOT SC/MOTUS. Suite indexes use sortable smart tables.
</div>
<section class="section">
  <h2>Report suites</h2>
  <p class="meta">Smart table: click column headers to sort.</p>
  <div id="ts-table-root" class="ts-table-root"></div>
</section>
<script>
  window.__CLUSTER_TABLE__ = {table_json};
</script>
{TANSTACK_BOOT}
<footer>
{COLOCATION_DISCLAIMER_HTML}
  <p class="disclaimer">See <code>README.md</code> in this package for methodology and regenerate commands.</p>
</footer>
</body>
</html>
"""


METHODOLOGY = {
    "colocator": (
        "<strong>Method:</strong> Cluster key = effective colocator "
        "<code>COALESCE(Addresses.colocator, Geocoding.colocator)</code>. "
        "Keys: <code>LL:lat:lon</code> or <code>PO:box:zip5</code> "
        "(PO collisions on same box+ZIP are intentional and kept). "
        "Excluded: bare <code>PO:box:</code> without ZIP, <code>FA:</code>, <code>VENDOR:</code>, "
        "geocode junk, and city-only samples (Dubai / Miami, Fl, ZIP with no street number) "
        "even when they have an LL: from bad geocoding. "
        "Pass rule: ≥1 <code>ofac_sanction</code>, ≥1 co-tenant, ≥1 street-quality address."
    ),
    "address": (
        "<strong>Method:</strong> Cluster key = <em>exact</em> "
        "<code>Addresses.canonical_address</code> string match. "
        "This suite is often sparse or empty: OFAC and 990/NPPES almost never share "
        "byte-identical suite wording (Suite 2185 vs Ste 2900, Street vs St). "
        "That is intentional — use <strong>colocator</strong> (building) or "
        "<strong>loose_colocator</strong> (0.5° grid) for real co-location. "
        "Pass: ≥1 OFAC + ≥1 co-tenant on the exact string."
    ),
    "zipcode": (
        "<strong>Method:</strong> Cluster key = <code>Addresses.zip_code</code> with "
        "<code>INNER JOIN Zips</code> (valid US ZIP catalog only; no REGEXP). "
        "Widen / context view — many unrelated entities share a ZIP. Prefer address/colocator "
        "for enforcement leads."
    ),
    "loose_colocator": (
        "<strong>Method:</strong> Cluster key = half-degree grid "
        "<code>LL:round(lat/0.5)*0.5:round(lon/0.5)*0.5</code> "
        "(same convention as grant_match / DOT loose). Prefers "
        "<code>Addresses.loose_colocator</code>, else derives from Geocoding or Addresses lat/lon. "
        "Wider than tight <code>LL:</code> building colocator, tighter than ZIP. "
        "Pass: ≥1 OFAC + ≥1 co-tenant on a US-state seed. "
        "Many co-tenants may be unrelated neighbors — see disclaimer."
    ),
}


def write_suite(
    con: duckdb.DuckDBPyConnection,
    slice_by: str,
    output_dir: Path,
    *,
    max_clusters: int,
    top_n: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(exist_ok=True)
    generated_at = datetime.now().isoformat(timespec="seconds")
    report_date = date.today().isoformat()

    print(f"  fetching clusters slice={slice_by} max={max_clusters}…", flush=True)
    clusters = fetch_clusters(con, slice_by, max_clusters=max_clusters)
    print(f"  → {len(clusters)} clusters", flush=True)

    # BMF-only EIN detail pages live under reports/eins/
    ein_dir = output_dir.parent / "eins"
    ein_dir.mkdir(parents=True, exist_ok=True)
    bmf_ofac_refs: dict[str, list[dict[str, Any]]] = {}
    bmf_rows: dict[str, dict[str, Any]] = {}

    for c in clusters:
        key = str(c["cluster_key"])
        slug = slugify(f"{slice_by}-{key}")
        c["slug"] = slug
        c["detail_file"] = f"{slug}.html"
        c["maps_url"] = maps_url(c.get("sample_address") or key)

        ofac = enrich_ofac_with_990(
            con, fetch_ofac_entities(con, slice_by, key, top_n=top_n)
        )
        c["ofac_with_ein"] = sum(1 for e in ofac if e.get("ein9"))
        c["ein_990_match"] = sum(1 for e in ofac if e.get("is_filer"))
        c["ein_bmf_match"] = sum(1 for e in ofac if e.get("is_bmf_only"))
        # Boost score when identity (EIN) matches exist
        c["score"] = (
            int(c.get("score") or 0)
            + int(c["ein_990_match"]) * 500
            + int(c["ein_bmf_match"]) * 100
        )
        for e in ofac:
            if e.get("is_bmf_only") and e.get("ein9"):
                ein9 = e["ein9"]
                bmf_ofac_refs.setdefault(ein9, []).append(e)
                if ein9 not in bmf_rows and e.get("charity_match"):
                    bmf_rows[ein9] = e["charity_match"]
        charities = fetch_charities(con, slice_by, key, top_n=top_n)
        grants = fetch_grants(con, slice_by, key, top_n=top_n)
        dots = fetch_dot(con, slice_by, key, top_n=min(top_n, 80))
        fec = fetch_fec_summary(con, slice_by, key)
        subs = fetch_sub_addresses(con, slice_by, key, top_n=40)

        html_out = render_detail(
            cluster=c,
            ofac=ofac,
            charities=charities,
            grants=grants,
            dots=dots,
            fec=fec,
            subs=subs,
            generated_at=generated_at,
            slice_by=slice_by,
        )
        (output_dir / c["detail_file"]).write_text(html_out, encoding="utf-8")

        (data_dir / f"{slug}.json").write_text(
            json.dumps(
                {
                    "cluster": {k: c[k] for k in c if k != "address_types" or True},
                    "ofac_entities": ofac,
                    "charities": charities,
                    "grants": grants,
                    "dot_carriers": dots,
                    "fec_counts": fec,
                    "sub_addresses": subs,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    for ein9, refs in bmf_ofac_refs.items():
        page = render_ein_detail(
            ein9=ein9,
            bmf=bmf_rows.get(ein9),
            ofac_refs=refs,
            generated_at=generated_at,
        )
        (ein_dir / f"{ein9}.html").write_text(page, encoding="utf-8")
    if bmf_ofac_refs:
        print(f"  wrote {len(bmf_ofac_refs)} BMF-only EIN detail pages → {ein_dir}", flush=True)

    index = render_index(
        slice_by=slice_by,
        clusters=clusters,
        generated_at=generated_at,
        report_date=report_date,
        methodology=METHODOLOGY.get(slice_by, ""),
    )
    (output_dir / "index.html").write_text(index, encoding="utf-8")
    (data_dir / "clusters.json").write_text(
        json.dumps(clusters, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "export_metadata.json").write_text(
        json.dumps(
            {
                "package": "ofac_reporting",
                "slice_by": slice_by,
                "generated_at": generated_at,
                "report_date": report_date,
                "n_clusters": len(clusters),
                "pass_rule": "≥1 ofac_sanction AND ≥1 co-tenant; street-quality for colocator/address",
                "fa_excluded": slice_by == "colocator",
                "street_quality_gate": slice_by in ("colocator", "address"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "slice_by": slice_by,
        "n_clusters": len(clusters),
        "output_dir": str(output_dir),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db-path", default=DEFAULT_DB)
    p.add_argument(
        "--slice-by",
        choices=["colocator", "loose_colocator", "address", "zipcode"],
        default=None,
        help="Single slice (default / --all-slices: all four)",
    )
    p.add_argument(
        "--all-slices",
        action="store_true",
        help="Write colocator + loose_colocator + address + zipcode",
    )
    p.add_argument(
        "--max-clusters",
        type=int,
        default=500,
        help="Cap per suite (default 500). OFAC is a catalog — raise to surface more cells.",
    )
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument(
        "--output-root",
        type=Path,
        default=SCRIPT_DIR / "reports",
        help="Root for suite dirs",
    )
    args = p.parse_args()

    slices = (
        ["colocator", "loose_colocator", "address", "zipcode"]
        if args.all_slices or args.slice_by is None
        else [args.slice_by]
    )
    if not Path(args.db_path).exists():
        print(f"DB not found: {args.db_path}", file=sys.stderr)
        return 1

    # Stable paths for public deploy (grumpytechbro.com) — no date suffix.
    # Generated-at timestamps still appear inside HTML metadata.
    print(f"Opening {args.db_path} (read_only)…", flush=True)
    con = open_db(args.db_path)
    suites_meta = []
    try:
        for sl in slices:
            out = args.output_root / f"ofac_{sl}_clusters"
            print(f"---- OFAC slice={sl} → {out} ----", flush=True)
            meta = write_suite(
                con, sl, out, max_clusters=args.max_clusters, top_n=args.top_n
            )
            rel = f"ofac_{sl}_clusters/index.html"
            suites_meta.append(
                {
                    "label": f"OFAC × {sl}",
                    "href": rel,
                    "n_clusters": meta["n_clusters"],
                    "notes": {
                        "colocator": "Building/PO; FA: excluded",
                        "loose_colocator": "0.5° LL grid (neighborhood widen)",
                        "address": "Exact street string",
                        "zipcode": "Valid US ZIP only (widen)",
                    }.get(sl, ""),
                }
            )
            print(f"---- OK {sl} clusters={meta['n_clusters']} ----", flush=True)
    finally:
        con.close()

    master = render_master_index(
        suites_meta, datetime.now().isoformat(timespec="seconds")
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "index.html").write_text(master, encoding="utf-8")
    print(f"Master index → {args.output_root / 'index.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
