#!/usr/bin/env python3
"""
generate_focus_reports.py — Cluster reports like trucking, for other entity stacks.

Same slice modes (address / colocator / zipcode / loose_colocator), different
primary entity focus and ranking:

  medicare       — NPPES practice/mailing + optional Medicare spending
  fec            — FEC contributors / committees / transactions / expenditures
  fec_committee  — committee street (line 1) ∩ charity / contractor / DOT / NPPES
  contractor     — 990 Schedule C contractors
  grants         — NGO grants (incoming) — grantee / grant addresses
  grants_out     — NGO grants (outgoing) — charity filer addresses × grants_to_others
  usg            — USG NGO funding — charity addresses × govt_amt

Usage:
  python generate_focus_reports.py --focus medicare --slice-by colocator
  python generate_focus_reports.py --focus fec --slice-by zipcode --max-clusters 100
  python generate_focus_reports.py --focus fec_committee --slice-by colocator --max-clusters 500
  python generate_focus_reports.py --focus contractor --slice-by address
  python generate_focus_reports.py --focus grants --slice-by loose_colocator
  python generate_focus_reports.py --focus grants_out --slice-by address
  python generate_focus_reports.py --focus usg --slice-by colocator
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
from mako.template import Template

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Reuse slice modes, maps, slugify, CSS, geocoding join logic from trucking reports.
from generate_address_reports import (  # type: ignore  # noqa: E402
    CSS,
    SLICE_MODES,
    fmt_money,
    google_maps_url,
    is_po_box,
    load_physical_notes,
    physical_note_for,
    mode_uses_alias,
    resolve_slice_mode,
    slugify_address,
    _member_filter_sql,
    fetch_charities,
    fetch_officers,
)

DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb"
MEDICARE_ROLLUP_SIDE = os.environ.get(
    "MEDICARE_ROLLUP_DB",
    "/Volumes/Data/final/medicare_provider_rollup.duckdb",
)


def ensure_medicare_rollup(conn: duckdb.DuckDBPyConnection) -> bool:
    """Ensure medicare_provider_rollup / _hcpcs are queryable.

    Prefer tables on the main DB; if missing (e.g. still building while main is
    locked), ATTACH the sidecar and expose TEMP VIEWs with the same names.
    """
    try:
        conn.execute("SELECT 1 FROM medicare_provider_rollup LIMIT 1")
        conn.execute("SELECT 1 FROM medicare_provider_hcpcs LIMIT 1")
        return True
    except Exception:
        pass
    side = MEDICARE_ROLLUP_SIDE
    if not os.path.exists(side):
        return False
    try:
        try:
            conn.execute("DETACH medroll")
        except Exception:
            pass
        conn.execute(f"ATTACH '{side}' AS medroll (READ_ONLY)")
        # Temp views work on read_only connections for query routing.
        conn.execute(
            "CREATE OR REPLACE TEMP VIEW medicare_provider_rollup AS "
            "SELECT * FROM medroll.medicare_provider_rollup"
        )
        conn.execute(
            "CREATE OR REPLACE TEMP VIEW medicare_provider_hcpcs AS "
            "SELECT * FROM medroll.medicare_provider_hcpcs"
        )
        conn.execute("SELECT 1 FROM medicare_provider_rollup LIMIT 1")
        return True
    except Exception as e:
        print(f"  medicare rollup attach failed: {e}", flush=True)
        return False


FOCUS_DOMAINS: dict[str, dict[str, Any]] = {
    "medicare": {
        "label": "Medicare / NPPES providers",
        "out_prefix": "medicare",
        "address_types": ("nppes_practice", "nppes_mailing"),
        # Admission is focus_count > 0 only; rank + max_clusters select the suite.
        "min_focus_default": 0,
        "min_multi_default": 0,
        "entity_title": "Medicare / NPPES providers",
        "amount_label": "Medicare paid (billing NPI)",
        "review_tag": "medicare",
        # Mill signal: high $ per HCPCS type (narrow codebooks with big spend).
        # Hospitals win pure $; paid/types surfaces personal-care / device stacks.
        "rank_metric": "paid_per_hcpcs_type",
        "rank_label": "Paid / HCPCS types",
    },
    "fec": {
        "label": "FEC political money",
        "out_prefix": "fec",
        "address_types": (
            "fec_contributor",
            "fec_committee",
            "fec_committee_transaction",
            "fec_operating_expenditure",
            "fec_candidate_spending",
        ),
        "min_focus_default": 0,
        "min_multi_default": 0,
        "entity_title": "FEC entities",
        "amount_label": "Contribution / transaction $",
        "review_tag": "fec",
        # Donor / entity density first — not committee mega-wires.
        "rank_metric": "focus_count",
        "rank_label": "FEC entity rows",
    },
    "fec_committee": {
        "label": "FEC committee streets × other types",
        "out_prefix": "fec_committee",
        "address_types": ("fec_committee",),
        "min_focus_default": 0,
        "min_multi_default": 0,
        "entity_title": "FEC committees",
        "amount_label": "—",
        "review_tag": "fec_committee",
        # Intersection first: how many of {charity, contractor, DOT, NPPES}.
        "rank_metric": "other_families",
        "rank_label": "Other-type families",
    },
    "contractor": {
        "label": "990 contractors",
        "out_prefix": "contractor",
        "address_types": ("contractor",),
        "min_focus_default": 0,
        "min_multi_default": 0,
        "entity_title": "Contractors",
        "amount_label": "Contractor payments",
        "review_tag": "contractor",
        # Prefer distinct street addresses (multi-suite shells), then row count / $.
        "rank_metric": "distinct_addresses",
        "rank_label": "Distinct addresses",
    },
    "grants": {
        "label": "NGO Grants (incoming)",
        "out_prefix": "grants",
        "address_types": ("grant",),
        "min_focus_default": 0,
        "min_multi_default": 0,
        "entity_title": "Incoming grants (grantee addresses)",
        "amount_label": "Grant amounts received",
        "review_tag": "grants",
        # $ after excluding name-suppressed / privacy rollups (big_pharma_subsidy.json).
        "rank_metric": "focus_amount",
        "rank_label": "Incoming grant $ (excl. suppressed names)",
    },
    "grants_out": {
        "label": "NGO Grants (outgoing)",
        "out_prefix": "grants_out",
        "address_types": ("charity",),
        "min_focus_default": 0,
        "min_multi_default": 0,
        "entity_title": "Charities granting out",
        "amount_label": "Grants to others (filer)",
        "review_tag": "grants_out",
        # Form 990 filer address × Charities.grants_to_others (multi-year sum).
        "rank_metric": "focus_amount",
        "rank_label": "Outgoing grant $ (grants_to_others)",
        "charity_amount_col": "grants_to_others",
    },
    "usg": {
        "label": "USG NGO Funding",
        "out_prefix": "usg",
        "address_types": ("charity",),
        "min_focus_default": 0,
        "min_multi_default": 0,
        "entity_title": "Charities with government funding",
        "amount_label": "Government funding (govt_amt)",
        "review_tag": "usg",
        # Form 990 filer address × Charities.govt_amt (multi-year sum).
        "rank_metric": "focus_amount",
        "rank_label": "USG / government $ (govt_amt)",
        "charity_amount_col": "govt_amt",
    },
}


def _type_in_sql(types: tuple[str, ...], col: str = "address_type") -> str:
    quoted = ", ".join(f"'{t}'" for t in types)
    return f"{col} IN ({quoted})"


def build_focus_cluster_sql(
    slice_by: str,
    focus: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    lat_long: bool = False,
) -> str:
    """Rank clusters by focus entity count + money metric."""
    domain = FOCUS_DOMAINS[focus]
    types = domain["address_types"]
    type_pred = _type_in_sql(types, "address_type")
    type_pred_k = _type_in_sql(types, "k.address_type")

    mode = resolve_slice_mode(slice_by, conn, lat_long=lat_long)
    key = mode["key_expr"]
    where = mode["where"]
    from_sql = mode.get("from_sql", "FROM Addresses")
    # mode_uses_alias: colocator (Geocoding) or zipcode (Zips) use Addresses a
    if mode_uses_alias(mode):
        canon, atype, owner, aid = (
            "a.canonical_address",
            "a.address_type",
            "a.owner_id",
            "a.address_id",
        )
        zipc, lat, lon, colo = (
            "a.zip_code",
            "a.latitude",
            "a.longitude",
            "a.colocator",
        )
    else:
        canon, atype, owner, aid = (
            "canonical_address",
            "address_type",
            "owner_id",
            "address_id",
        )
        zipc, lat, lon, colo = (
            "zip_code",
            "latitude",
            "longitude",
            "colocator",
        )

    # Money metric join varies by focus.
    # Medicare: join NPI-level rollup (not 230M line-level spending).
    if focus == "medicare":
        if not ensure_medicare_rollup(conn):
            # No rollup yet — empty money (rank falls back to focus_count via ties)
            money_cte = """
money AS (
    SELECT
        CAST(NULL AS VARCHAR) AS cluster_key,
        CAST(0 AS DOUBLE) AS focus_amount,
        CAST(0 AS BIGINT) AS hcpcs_type_count_sum,
        CAST(0 AS BIGINT) AS total_claims_sum,
        CAST(0 AS BIGINT) AS npi_with_spend,
        CAST(0 AS DOUBLE) AS paid_per_hcpcs_type
    WHERE FALSE
)
"""
        else:
            money_cte = f"""
money AS (
    SELECT
        k.cluster_key,
        COALESCE(SUM(r.total_paid), 0)::DOUBLE AS focus_amount,
        COALESCE(SUM(r.hcpcs_type_count), 0)::BIGINT AS hcpcs_type_count_sum,
        COALESCE(SUM(r.total_claims), 0)::BIGINT AS total_claims_sum,
        COUNT(DISTINCT r.npi)::BIGINT AS npi_with_spend,
        -- Cluster intensity: total $ / total HCPCS type rows across NPIs.
        -- High when a few codes carry most of the money (mill-shaped).
        CASE
            WHEN COALESCE(SUM(r.hcpcs_type_count), 0) > 0
            THEN COALESCE(SUM(r.total_paid), 0)::DOUBLE
                 / SUM(r.hcpcs_type_count)::DOUBLE
            ELSE 0::DOUBLE
        END AS paid_per_hcpcs_type
    FROM keyed k
    INNER JOIN medicare_providers m
        ON m.id = k.owner_id
       AND k.address_type IN ('nppes_practice', 'nppes_mailing')
    INNER JOIN medicare_provider_rollup r ON r.npi = m.npi
    GROUP BY k.cluster_key
)
"""
    elif focus == "fec":
        # $ still computed for display; default rank is focus_count (density).
        money_cte = f"""
money AS (
    SELECT
        cluster_key,
        SUM(amt)::DOUBLE AS focus_amount,
        COUNT(DISTINCT CASE WHEN kind = 'contributor' THEN entity_key END)::BIGINT
            AS distinct_contributors
    FROM (
        SELECT
            k.cluster_key,
            COALESCE(f.contribution_amount, 0) AS amt,
            'contributor' AS kind,
            COALESCE(NULLIF(TRIM(f.contributor_name), ''), CAST(f.id AS VARCHAR)) AS entity_key
        FROM keyed k
        INNER JOIN fec_individual_contributions f
            ON f.id = k.owner_id AND k.address_type = 'fec_contributor'
        UNION ALL
        SELECT
            k.cluster_key,
            COALESCE(t.transaction_amount, 0),
            'transaction',
            COALESCE(NULLIF(TRIM(t.fec_cmte_id), ''), CAST(t.id AS VARCHAR))
        FROM keyed k
        INNER JOIN fec_committee_transactions t
            ON t.id = k.owner_id AND k.address_type = 'fec_committee_transaction'
        UNION ALL
        SELECT
            k.cluster_key,
            COALESCE(o.expenditure_amount, 0),
            'expenditure',
            COALESCE(NULLIF(TRIM(o.fec_cmte_id), ''), CAST(o.id AS VARCHAR))
        FROM keyed k
        INNER JOIN fec_operating_expenditures o
            ON o.id = k.owner_id AND k.address_type = 'fec_operating_expenditure'
        UNION ALL
        SELECT
            k.cluster_key,
            COALESCE(c.spending_amount, 0),
            'candidate',
            COALESCE(NULLIF(TRIM(c.fec_cand_id), ''), CAST(c.id AS VARCHAR))
        FROM keyed k
        INNER JOIN fec_candidate_spendings c
            ON c.id = k.owner_id AND k.address_type = 'fec_candidate_spending'
    ) u
    GROUP BY cluster_key
)
"""
    elif focus == "contractor":
        money_cte = f"""
money AS (
    SELECT
        k.cluster_key,
        COALESCE(SUM(c.amount), 0)::DOUBLE AS focus_amount
    FROM keyed k
    INNER JOIN Contractors c
        ON c.contractor_id = k.owner_id AND k.address_type = 'contractor'
    GROUP BY k.cluster_key
)
"""
    elif focus == "grants":
        # Incoming grants — exclude name-suppressed / privacy rollups from $
        from grant_suppress import suppressed_sql_predicate  # noqa: WPS433

        keep = suppressed_sql_predicate("g.grantee_name")
        money_cte = f"""
money AS (
    SELECT
        k.cluster_key,
        COALESCE(SUM(g.grant_amt), 0)::DOUBLE AS focus_amount
    FROM keyed k
    INNER JOIN Grants g
        ON g.grant_id = k.owner_id AND k.address_type = 'grant'
    WHERE {keep}
    GROUP BY k.cluster_key
)
"""
    elif focus == "fec_committee":
        # Seeded from ~7k committee rows; dollars live on other FEC types.
        money_cte = """
money AS (
    SELECT CAST(NULL AS VARCHAR) AS cluster_key, 0::DOUBLE AS focus_amount
    WHERE FALSE
)
"""
    elif focus in ("grants_out", "usg"):
        # Charity filer addresses × Charities.grants_to_others or govt_amt.
        amt_col = domain.get("charity_amount_col") or (
            "grants_to_others" if focus == "grants_out" else "govt_amt"
        )
        if amt_col not in ("grants_to_others", "govt_amt"):
            raise ValueError(f"unsupported charity amount column: {amt_col}")
        money_cte = f"""
money AS (
    SELECT
        k.cluster_key,
        COALESCE(SUM(c.{amt_col}), 0)::DOUBLE AS focus_amount
    FROM keyed k
    INNER JOIN Charities c
        ON c.charity_id = k.owner_id AND k.address_type = 'charity'
    GROUP BY k.cluster_key
)
"""
    else:
        raise ValueError(f"unknown focus for money CTE: {focus}")

    # Per-focus ORDER BY for "top" clusters
    rank_metric = domain.get("rank_metric", "focus_count")
    if focus == "medicare":
        # paid/types first (mill intensity); then raw $; prefer narrower books on ties.
        order_by = (
            "COALESCE(m.paid_per_hcpcs_type, 0) DESC, "
            "COALESCE(m.focus_amount, 0) DESC, "
            "COALESCE(m.hcpcs_type_count_sum, 0) ASC, "
            "COALESCE(m.npi_with_spend, 0) DESC, "
            "b.focus_count DESC"
        )
        money_select_extra = (
            ", COALESCE(m.hcpcs_type_count_sum, 0) AS hcpcs_type_count_sum, "
            "COALESCE(m.total_claims_sum, 0) AS total_claims_sum, "
            "COALESCE(m.npi_with_spend, 0) AS npi_with_spend, "
            "COALESCE(m.paid_per_hcpcs_type, 0) AS paid_per_hcpcs_type, "
            "0::BIGINT AS distinct_contributors"
        )
    elif focus == "fec":
        # Density of FEC rows first; $ secondary so mega-wires don't own the list.
        order_by = (
            "b.focus_count DESC, "
            "COALESCE(m.distinct_contributors, 0) DESC, "
            "COALESCE(m.focus_amount, 0) DESC, "
            "b.total_rows DESC"
        )
        money_select_extra = (
            ", 0::BIGINT AS hcpcs_type_count_sum, "
            "0::BIGINT AS total_claims_sum, "
            "0::BIGINT AS npi_with_spend, "
            "0::DOUBLE AS paid_per_hcpcs_type, "
            "COALESCE(m.distinct_contributors, 0) AS distinct_contributors"
        )
    elif rank_metric == "focus_amount":
        order_by = (
            "COALESCE(m.focus_amount, 0) DESC, b.focus_count DESC, b.total_rows DESC"
        )
        money_select_extra = (
            ", 0::BIGINT AS hcpcs_type_count_sum, "
            "0::BIGINT AS total_claims_sum, "
            "0::BIGINT AS npi_with_spend, "
            "0::DOUBLE AS paid_per_hcpcs_type, "
            "0::BIGINT AS distinct_contributors"
        )
    elif rank_metric == "other_families":
        order_by = (
            "("
            "(CASE WHEN b.charity_count > 0 THEN 1 ELSE 0 END) + "
            "(CASE WHEN b.contractor_count > 0 THEN 1 ELSE 0 END) + "
            "(CASE WHEN b.dot_carrier_count > 0 THEN 1 ELSE 0 END) + "
            "(CASE WHEN b.medicare_count > 0 THEN 1 ELSE 0 END)"
            ") DESC, "
            "(b.charity_count + b.contractor_count + b.dot_carrier_count "
            "+ b.medicare_count) DESC, "
            "b.focus_count DESC, b.total_rows DESC"
        )
        money_select_extra = (
            ", 0::BIGINT AS hcpcs_type_count_sum, "
            "0::BIGINT AS total_claims_sum, "
            "0::BIGINT AS npi_with_spend, "
            "0::DOUBLE AS paid_per_hcpcs_type, "
            "0::BIGINT AS distinct_contributors"
        )
    elif rank_metric == "distinct_addresses":
        order_by = (
            "b.distinct_focus_addresses DESC, b.focus_count DESC, "
            "COALESCE(m.focus_amount, 0) DESC, b.total_rows DESC"
        )
        money_select_extra = (
            ", 0::BIGINT AS hcpcs_type_count_sum, "
            "0::BIGINT AS total_claims_sum, "
            "0::BIGINT AS npi_with_spend, "
            "0::DOUBLE AS paid_per_hcpcs_type, "
            "0::BIGINT AS distinct_contributors"
        )
    else:
        order_by = (
            "b.focus_count DESC, COALESCE(m.focus_amount, 0) DESC, b.total_rows DESC"
        )
        money_select_extra = (
            ", 0::BIGINT AS hcpcs_type_count_sum, "
            "0::BIGINT AS total_claims_sum, "
            "0::BIGINT AS npi_with_spend, "
            "0::DOUBLE AS paid_per_hcpcs_type, "
            "0::BIGINT AS distinct_contributors"
        )

    # FEC committee × other types: seed ~7k committee line-1 streets, then expand
    # co-tenants only at those keys. Never scan 29M contributor blobs.
    if focus == "fec_committee":
        line1 = "a.address_line1" if mode_uses_alias(mode) else "address_line1"
        return f"""
WITH committee_keyed AS (
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
      AND {atype} = 'fec_committee'
      AND {line1} IS NOT NULL
      AND TRIM({line1}) != ''
      AND ({key}) IS NOT NULL
      AND TRIM(CAST(({key}) AS VARCHAR)) != ''
),
candidates AS (
    SELECT
        cluster_key,
        COUNT(*)::BIGINT AS focus_count,
        COUNT(DISTINCT COALESCE(NULLIF(TRIM(canonical_address), ''),
            CAST(address_id AS VARCHAR)))::BIGINT AS distinct_focus_addresses,
        ANY_VALUE(CASE
            WHEN canonical_address IS NOT NULL AND TRIM(canonical_address) != ''
            THEN canonical_address END) AS sample_address,
        ANY_VALUE(NULLIF(TRIM(zip_code), '')) AS zip_code,
        ANY_VALUE(latitude) AS latitude,
        ANY_VALUE(longitude) AS longitude,
        ANY_VALUE(NULLIF(TRIM(colocator), '')) AS colocator
    FROM committee_keyed
    GROUP BY cluster_key
),
keyed AS (
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
      AND ({key}) IN (SELECT cluster_key FROM candidates)
),
base AS (
    SELECT
        cluster_key,
        COUNT(*)::BIGINT AS total_rows,
        COUNT(DISTINCT address_type)::BIGINT AS multi_type_count,
        LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
        SUM(CASE WHEN address_type = 'dot_carrier_phy'
                 THEN 1 ELSE 0 END)::BIGINT AS dot_carrier_count,
        SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_count,
        SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_count,
        SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_count,
        SUM(CASE WHEN address_type = 'contractor' THEN 1 ELSE 0 END)::BIGINT AS contractor_count,
        SUM(CASE WHEN address_type LIKE 'fec%' THEN 1 ELSE 0 END)::BIGINT AS fec_count,
        SUM(CASE WHEN address_type IN ('nppes_practice', 'nppes_mailing')
                 THEN 1 ELSE 0 END)::BIGINT AS medicare_count
    FROM keyed
    GROUP BY cluster_key
),
charity_signals AS (
    SELECT
        k.cluster_key,
        MAX(c.grift_ratio) AS max_grift_ratio,
        SUM(CASE
            WHEN UPPER(CAST(c.domestic_misrep_flag AS VARCHAR))
                 IN ('TRUE', '1', 'Y', 'YES', 'T')
            THEN 1 ELSE 0
        END)::BIGINT AS misrep_count
    FROM keyed k
    INNER JOIN Charities c ON c.charity_id = k.owner_id AND k.address_type = 'charity'
    GROUP BY k.cluster_key
)
SELECT
    c.cluster_key,
    c.sample_address,
    COALESCE(b.total_rows, c.focus_count) AS total_rows,
    COALESCE(b.multi_type_count, 1) AS multi_type_count,
    COALESCE(b.address_types, CAST(['fec_committee'] AS VARCHAR[])) AS address_types,
    c.focus_count,
    c.distinct_focus_addresses,
    COALESCE(b.dot_carrier_count, 0) AS dot_carrier_count,
    COALESCE(b.charity_count, 0) AS charity_count,
    COALESCE(b.grant_count, 0) AS grant_count,
    COALESCE(b.officer_count, 0) AS officer_count,
    COALESCE(b.contractor_count, 0) AS contractor_count,
    COALESCE(b.fec_count, c.focus_count) AS fec_count,
    COALESCE(b.medicare_count, 0) AS medicare_count,
    cs.max_grift_ratio,
    COALESCE(cs.misrep_count, 0) AS misrep_count,
    0::DOUBLE AS focus_amount
    {money_select_extra},
    c.zip_code,
    c.latitude,
    c.longitude,
    c.colocator
FROM candidates c
LEFT JOIN base b ON b.cluster_key = c.cluster_key
LEFT JOIN charity_signals cs ON cs.cluster_key = c.cluster_key
WHERE c.focus_count > 0
  AND (
      COALESCE(b.charity_count, 0) > 0
      OR COALESCE(b.contractor_count, 0) > 0
      OR COALESCE(b.dot_carrier_count, 0) > 0
      OR COALESCE(b.medicare_count, 0) > 0
  )
  AND (? <= 0 OR TRUE)
  AND (? <= 0 OR TRUE)
  AND (? <= 0 OR c.focus_count >= ?)
  AND (
      ? = 0
      OR COALESCE(cs.max_grift_ratio, 0) > 5
      OR COALESCE(cs.misrep_count, 0) > 0
  )
ORDER BY
    (
        (CASE WHEN COALESCE(b.charity_count, 0) > 0 THEN 1 ELSE 0 END) +
        (CASE WHEN COALESCE(b.contractor_count, 0) > 0 THEN 1 ELSE 0 END) +
        (CASE WHEN COALESCE(b.dot_carrier_count, 0) > 0 THEN 1 ELSE 0 END) +
        (CASE WHEN COALESCE(b.medicare_count, 0) > 0 THEN 1 ELSE 0 END)
    ) DESC,
    (COALESCE(b.charity_count, 0) + COALESCE(b.contractor_count, 0)
     + COALESCE(b.dot_carrier_count, 0) + COALESCE(b.medicare_count, 0)) DESC,
    c.focus_count DESC
LIMIT ?
"""

    # Charity $ focuses (grants_out / usg): rank from charity rows only (~3M), then
    # expand multi-type / co-tenant counts for the short candidate list. Full-table
    # keyed scans OOM on the 80M+ Addresses heap when memory is tight.
    if focus in ("grants_out", "usg"):
        amt_col = domain.get("charity_amount_col") or (
            "grants_to_others" if focus == "grants_out" else "govt_amt"
        )
        return f"""
WITH charity_keyed AS (
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
      AND {atype} = 'charity'
      AND ({key}) IS NOT NULL
      AND TRIM(CAST(({key}) AS VARCHAR)) != ''
),
money AS (
    SELECT
        k.cluster_key,
        COALESCE(SUM(c.{amt_col}), 0)::DOUBLE AS focus_amount,
        COUNT(*)::BIGINT AS focus_count,
        COUNT(DISTINCT COALESCE(NULLIF(TRIM(k.canonical_address), ''),
            CAST(k.address_id AS VARCHAR)))::BIGINT AS distinct_focus_addresses,
        ANY_VALUE(CASE
            WHEN k.canonical_address IS NOT NULL AND TRIM(k.canonical_address) != ''
            THEN k.canonical_address END) AS sample_address,
        ANY_VALUE(NULLIF(TRIM(k.zip_code), '')) AS zip_code,
        ANY_VALUE(k.latitude) AS latitude,
        ANY_VALUE(k.longitude) AS longitude,
        ANY_VALUE(NULLIF(TRIM(k.colocator), '')) AS colocator,
        MAX(c.grift_ratio) AS max_grift_ratio,
        SUM(CASE
            WHEN UPPER(CAST(c.domestic_misrep_flag AS VARCHAR))
                 IN ('TRUE', '1', 'Y', 'YES', 'T')
            THEN 1 ELSE 0
        END)::BIGINT AS misrep_count
    FROM charity_keyed k
    INNER JOIN Charities c ON c.charity_id = k.owner_id
    GROUP BY k.cluster_key
),
candidates AS (
    -- Bind signature matches fetch_clusters_focus:
    --   min_multi×2, min_focus×2, grift_flag, limit
    -- Multi-type floor is applied after base expand (legacy; usually 0).
    SELECT *
    FROM money
    WHERE focus_count > 0
      AND (? <= 0 OR TRUE)
      AND (? <= 0 OR TRUE)
      AND (? <= 0 OR focus_count >= ?)
      AND (
          ? = 0
          OR COALESCE(max_grift_ratio, 0) > 5
          OR COALESCE(misrep_count, 0) > 0
      )
    ORDER BY focus_amount DESC, focus_count DESC
    LIMIT ?
),
keyed AS (
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
      AND ({key}) IN (SELECT cluster_key FROM candidates)
),
base AS (
    SELECT
        cluster_key,
        COUNT(*)::BIGINT AS total_rows,
        COUNT(DISTINCT address_type)::BIGINT AS multi_type_count,
        LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
        SUM(CASE WHEN address_type = 'dot_carrier_phy'
                 THEN 1 ELSE 0 END)::BIGINT AS dot_carrier_count,
        SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_count,
        SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_count,
        SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_count,
        SUM(CASE WHEN address_type = 'contractor' THEN 1 ELSE 0 END)::BIGINT AS contractor_count,
        SUM(CASE WHEN address_type LIKE 'fec%' THEN 1 ELSE 0 END)::BIGINT AS fec_count,
        SUM(CASE WHEN address_type IN ('nppes_practice', 'nppes_mailing')
                 THEN 1 ELSE 0 END)::BIGINT AS medicare_count
    FROM keyed
    GROUP BY cluster_key
)
SELECT
    c.cluster_key,
    c.sample_address,
    COALESCE(b.total_rows, c.focus_count) AS total_rows,
    COALESCE(b.multi_type_count, 1) AS multi_type_count,
    COALESCE(b.address_types, CAST(['charity'] AS VARCHAR[])) AS address_types,
    c.focus_count,
    c.distinct_focus_addresses,
    COALESCE(b.dot_carrier_count, 0) AS dot_carrier_count,
    COALESCE(b.charity_count, c.focus_count) AS charity_count,
    COALESCE(b.grant_count, 0) AS grant_count,
    COALESCE(b.officer_count, 0) AS officer_count,
    COALESCE(b.contractor_count, 0) AS contractor_count,
    COALESCE(b.fec_count, 0) AS fec_count,
    COALESCE(b.medicare_count, 0) AS medicare_count,
    c.max_grift_ratio,
    COALESCE(c.misrep_count, 0) AS misrep_count,
    COALESCE(c.focus_amount, 0) AS focus_amount
    {money_select_extra},
    c.zip_code,
    c.latitude,
    c.longitude,
    c.colocator
FROM candidates c
LEFT JOIN base b ON b.cluster_key = c.cluster_key
ORDER BY COALESCE(c.focus_amount, 0) DESC, c.focus_count DESC
"""

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
        COUNT(*)::BIGINT AS total_rows,
        COUNT(DISTINCT address_type)::BIGINT AS multi_type_count,
        LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
        SUM(CASE WHEN {type_pred} THEN 1 ELSE 0 END)::BIGINT AS focus_count,
        COUNT(DISTINCT CASE WHEN {type_pred}
            THEN COALESCE(NULLIF(TRIM(canonical_address), ''), CAST(address_id AS VARCHAR))
            END)::BIGINT AS distinct_focus_addresses,
        SUM(CASE WHEN address_type = 'dot_carrier_phy'
                 THEN 1 ELSE 0 END)::BIGINT AS dot_carrier_count,
        SUM(CASE WHEN address_type = 'charity' THEN 1 ELSE 0 END)::BIGINT AS charity_count,
        SUM(CASE WHEN address_type = 'grant' THEN 1 ELSE 0 END)::BIGINT AS grant_count,
        SUM(CASE WHEN address_type = 'officer' THEN 1 ELSE 0 END)::BIGINT AS officer_count,
        SUM(CASE WHEN address_type = 'contractor' THEN 1 ELSE 0 END)::BIGINT AS contractor_count,
        SUM(CASE WHEN address_type LIKE 'fec%' THEN 1 ELSE 0 END)::BIGINT AS fec_count,
        SUM(CASE WHEN address_type IN ('nppes_practice', 'nppes_mailing')
                 THEN 1 ELSE 0 END)::BIGINT AS medicare_count,
        ANY_VALUE(CASE
            WHEN canonical_address IS NOT NULL AND TRIM(canonical_address) != ''
            THEN canonical_address END) AS sample_address,
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
            WHEN UPPER(CAST(c.domestic_misrep_flag AS VARCHAR))
                 IN ('TRUE', '1', 'Y', 'YES', 'T')
            THEN 1 ELSE 0
        END)::BIGINT AS misrep_count
    FROM keyed k
    INNER JOIN Charities c ON c.charity_id = k.owner_id AND k.address_type = 'charity'
    GROUP BY k.cluster_key
),
{money_cte}
SELECT
    b.cluster_key,
    b.sample_address,
    b.total_rows,
    b.multi_type_count,
    b.address_types,
    b.focus_count,
    b.distinct_focus_addresses,
    b.dot_carrier_count,
    b.charity_count,
    b.grant_count,
    b.officer_count,
    b.contractor_count,
    b.fec_count,
    b.medicare_count,
    cs.max_grift_ratio,
    COALESCE(cs.misrep_count, 0) AS misrep_count,
    COALESCE(m.focus_amount, 0) AS focus_amount
    {money_select_extra},
    b.zip_code,
    b.latitude,
    b.longitude,
    b.colocator
FROM base b
LEFT JOIN charity_signals cs ON cs.cluster_key = b.cluster_key
LEFT JOIN money m ON m.cluster_key = b.cluster_key
WHERE
    -- Domain membership only: at least one focus address row at this key.
    -- No min_multi / min_focus density floors — rank metric + LIMIT pick the suite.
    b.focus_count > 0
    -- Optional legacy floors (0 = off). Prefer omitting; use rank + max_clusters.
    AND (? <= 0 OR b.multi_type_count >= ?)
    AND (? <= 0 OR b.focus_count >= ?)
    AND (
        ? = 0
        OR COALESCE(cs.max_grift_ratio, 0) > 5
        OR COALESCE(cs.misrep_count, 0) > 0
    )
ORDER BY {order_by}
LIMIT ?
"""


def suspicion_score_focus(cluster: dict, focus: str) -> int:
    fc = int(cluster.get("focus_count") or 0)
    amt = float(cluster.get("focus_amount") or 0)
    multi = int(cluster.get("multi_type_count") or 0)
    score = fc * 2.0
    if amt > 0:
        # log-ish scale: $1M → +200
        score += min(5000, (amt / 1_000_000.0) * 200)
    if multi <= 2 and fc >= 20:
        score += 250  # mono-type stack
    if cluster.get("phy_is_po_box"):
        score += 400
    if (cluster.get("max_grift_ratio") or 0) > 5:
        score += 150
    if focus == "fec" and fc >= 100:
        score += 100
    if focus == "fec_committee":
        families = sum(
            1
            for k in (
                "charity_count",
                "contractor_count",
                "dot_carrier_count",
                "medicare_count",
            )
            if int(cluster.get(k) or 0) > 0
        )
        score += families * 80
    return int(score)


def reason_codes_focus(cluster: dict, min_multi: int, min_focus: int, focus: str) -> list[str]:
    codes = []
    if cluster["multi_type_count"] >= min_multi:
        codes.append("multi_type")
    if cluster["focus_count"] >= min_focus:
        codes.append(f"{focus}_stack")
    if (cluster.get("max_grift_ratio") or 0) > 5:
        codes.append("high_grift")
    if cluster.get("misrep_count", 0) > 0:
        codes.append("domestic_misrep")
    if cluster.get("phy_is_po_box"):
        codes.append("phy_po_box")
    if float(cluster.get("focus_amount") or 0) >= 1_000_000:
        codes.append("high_dollar")
    if focus == "fec_committee":
        if int(cluster.get("charity_count") or 0) > 0:
            codes.append("cross_charity")
        if int(cluster.get("contractor_count") or 0) > 0:
            codes.append("cross_contractor")
        if int(cluster.get("dot_carrier_count") or 0) > 0:
            codes.append("cross_dot")
        if int(cluster.get("medicare_count") or 0) > 0:
            codes.append("cross_nppes")
    return codes or ["threshold"]


def fetch_clusters_focus(
    conn,
    slice_by: str,
    focus: str,
    min_multi: int,
    min_focus: int,
    require_grift: bool,
    limit: int,
    *,
    lat_long: bool = False,
) -> list[dict[str, Any]]:
    domain = FOCUS_DOMAINS[focus]
    rank_metric = domain.get("rank_metric", "focus_count")
    # Grants (incoming): over-fetch candidates then keep top `limit` by clean $
    # (already filtered in SQL). Still over-fetch so borderline multi_type-only
    # clusters with suppressed-only $ don't crowd out real ones after any post-filter.
    sql_limit = limit
    if focus == "grants":
        sql_limit = max(limit * 10, min(1000, limit * 15))

    sql = build_focus_cluster_sql(slice_by, focus, conn, lat_long=lat_long)
    # Bind: multi floor (twice), focus floor (twice), grift flag, limit
    rows = conn.execute(
        sql,
        [
            int(min_multi or 0),
            int(min_multi or 0),
            int(min_focus or 0),
            int(min_focus or 0),
            1 if require_grift else 0,
            sql_limit,
        ],
    ).fetchall()
    cols = [
        "cluster_key",
        "sample_address",
        "total_rows",
        "multi_type_count",
        "address_types",
        "focus_count",
        "distinct_focus_addresses",
        "dot_carrier_count",
        "charity_count",
        "grant_count",
        "officer_count",
        "contractor_count",
        "fec_count",
        "medicare_count",
        "max_grift_ratio",
        "misrep_count",
        "focus_amount",
        "hcpcs_type_count_sum",
        "total_claims_sum",
        "npi_with_spend",
        "paid_per_hcpcs_type",
        "distinct_contributors",
        "zip_code",
        "latitude",
        "longitude",
        "colocator",
    ]
    out = []
    for row in rows:
        c = dict(zip(cols, row))
        if isinstance(c["address_types"], str):
            c["address_types"] = [
                t.strip() for t in c["address_types"].strip("[]").split(",") if t.strip()
            ]
        c["canonical_address"] = str(c["cluster_key"])
        c["slice_by"] = slice_by
        c["focus"] = focus
        c["focus_amount_fmt"] = fmt_money(c.get("focus_amount"))
        # Surface rank metric for tables / scoring
        if rank_metric == "distinct_addresses":
            c["rank_metric_value"] = int(c.get("distinct_focus_addresses") or 0)
            c["rank_metric_fmt"] = f"{c['rank_metric_value']:,}"
        elif rank_metric == "paid_per_hcpcs_type":
            c["rank_metric_value"] = float(c.get("paid_per_hcpcs_type") or 0)
            c["rank_metric_fmt"] = fmt_money(c["rank_metric_value"])
            c["paid_per_hcpcs_type_fmt"] = c["rank_metric_fmt"]
        elif rank_metric == "focus_amount":
            c["rank_metric_value"] = float(c.get("focus_amount") or 0)
            c["rank_metric_fmt"] = c["focus_amount_fmt"]
        elif rank_metric == "other_families":
            families = sum(
                1
                for k in (
                    "charity_count",
                    "contractor_count",
                    "dot_carrier_count",
                    "medicare_count",
                )
                if int(c.get(k) or 0) > 0
            )
            c["other_families"] = families
            c["rank_metric_value"] = families
            c["rank_metric_fmt"] = str(families)
        else:
            c["rank_metric_value"] = int(c.get("focus_count") or 0)
            c["rank_metric_fmt"] = f"{c['rank_metric_value']:,}"
        out.append(c)

    # Final cut to requested limit (SQL already ordered by rank metric)
    return out[:limit]


def fetch_focus_entities(
    conn,
    slice_by: str,
    cluster_key: str,
    focus: str,
    top_n: int,
    *,
    lat_long: bool = False,
) -> list[dict]:
    key_expr, where, gjoin = _member_filter_sql(slice_by, conn, lat_long=lat_long)
    types = FOCUS_DOMAINS[focus]["address_types"]
    type_sql = _type_in_sql(types, "a.address_type")

    if focus == "medicare":
        # Prefer rollup (NPI-level $ + HCPCS type count); fall back to providers only.
        has_rollup = ensure_medicare_rollup(conn)

        if has_rollup:
            rows = conn.execute(
                f"""
                SELECT
                    m.npi,
                    COALESCE(
                        NULLIF(TRIM(m.organization_name), ''),
                        NULLIF(TRIM(r.organization_name), ''),
                        NULLIF(TRIM(COALESCE(m.provider_first_name,'') || ' ' ||
                             COALESCE(m.provider_last_name,'')), ''),
                        m.npi
                    ) AS display_name,
                    m.entity_type_code,
                    m.provider_credential,
                    a.address_type,
                    a.canonical_address,
                    COALESCE(r.total_paid, 0)::DOUBLE AS paid,
                    COALESCE(r.hcpcs_type_count, 0)::BIGINT AS hcpcs_types,
                    COALESCE(r.total_claims, 0)::BIGINT AS claims,
                    r.top_hcpcs_code,
                    COALESCE(r.top_hcpcs_paid, 0)::DOUBLE AS top_hcpcs_paid
                FROM Addresses a
                {gjoin}
                JOIN medicare_providers m ON m.id = a.owner_id
                LEFT JOIN medicare_provider_rollup r ON r.npi = m.npi
                WHERE ({key_expr}) = ?
                  AND ({where})
                  AND {type_sql}
                ORDER BY COALESCE(r.total_paid, 0) DESC NULLS LAST, display_name
                LIMIT ?
                """,
                [cluster_key, top_n],
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT
                    m.npi,
                    COALESCE(m.organization_name,
                        TRIM(COALESCE(m.provider_first_name,'') || ' ' ||
                             COALESCE(m.provider_last_name,''))) AS display_name,
                    m.entity_type_code,
                    m.provider_credential,
                    a.address_type,
                    a.canonical_address,
                    0::DOUBLE, 0::BIGINT, 0::BIGINT, NULL, 0::DOUBLE
                FROM Addresses a
                {gjoin}
                JOIN medicare_providers m ON m.id = a.owner_id
                WHERE ({key_expr}) = ?
                  AND ({where})
                  AND {type_sql}
                ORDER BY display_name
                LIMIT ?
                """,
                [cluster_key, top_n],
            ).fetchall()

        npis = [r[0] for r in rows if r[0]]
        hcpcs_by_npi: dict[str, list[dict]] = {str(n): [] for n in npis}
        from provider_pages import format_hcpcs_label, load_hcpcs_labels  # noqa: WPS433

        hcpcs_labels = load_hcpcs_labels(conn)
        if npis and has_rollup:
            try:
                h_rows = conn.execute(
                    """
                    SELECT npi, hcpcs_code, total_claims, total_paid, total_beneficiaries
                    FROM medicare_provider_hcpcs
                    WHERE npi IN (SELECT UNNEST(?::VARCHAR[]))
                    ORDER BY npi, total_paid DESC NULLS LAST
                    """,
                    [npis],
                ).fetchall()
                for npi, code, claims, paid, bens in h_rows:
                    bucket = hcpcs_by_npi.setdefault(str(npi), [])
                    if len(bucket) >= 12:
                        continue  # cap types shown per provider on cluster page
                    raw = code or "—"
                    bucket.append(
                        {
                            "hcpcs_code": raw,
                            "hcpcs_label": format_hcpcs_label(raw, hcpcs_labels),
                            "claims": int(claims or 0),
                            "paid": float(paid or 0),
                            "paid_fmt": fmt_money(paid),
                            "beneficiaries": int(bens or 0),
                        }
                    )
            except Exception:
                pass

        out = []
        for (
            npi,
            name,
            etc,
            cred,
            at,
            canon,
            paid,
            htypes,
            claims,
            top_code,
            top_paid,
        ) in rows:
            paid_f = float(paid or 0)
            top_label = format_hcpcs_label(top_code, hcpcs_labels) if top_code else None
            detail_bits = [
                f"NPI {npi}",
                f"entity={etc or '—'}",
            ]
            if cred:
                detail_bits.append(str(cred))
            if htypes:
                detail_bits.append(f"{int(htypes)} HCPCS types")
            if claims:
                detail_bits.append(f"{int(claims):,} claims")
            if top_label:
                detail_bits.append(
                    f"top {top_label} {fmt_money(top_paid) if top_paid else ''}".strip()
                )
            out.append(
                {
                    "id": npi,
                    "name": name or "(unnamed)",
                    "detail": " · ".join(detail_bits),
                    "amount": paid_f,
                    "amount_fmt": fmt_money(paid_f) if paid_f else "—",
                    "address_type": at,
                    "canonical_address": (canon or "").strip() or "(no street)",
                    "hcpcs_type_count": int(htypes or 0),
                    "total_claims": int(claims or 0),
                    "top_hcpcs_code": top_code,
                    "top_hcpcs_label": top_label,
                    "hcpcs": hcpcs_by_npi.get(str(npi), []),
                }
            )
        return out

    if focus == "fec_committee":
        line1 = "a.address_line1"
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(c.name), ''), c.fec_cmte_id) AS name,
                c.fec_cmte_id,
                NULLIF(TRIM(c.treasurer_name), '') AS treasurer,
                a.canonical_address
            FROM Addresses a
            {gjoin}
            JOIN fec_committees c ON c.id = a.owner_id
            WHERE ({key_expr}) = ?
              AND ({where})
              AND a.address_type = 'fec_committee'
              AND {line1} IS NOT NULL
              AND TRIM({line1}) != ''
            ORDER BY name
            LIMIT ?
            """,
            [cluster_key, top_n],
        ).fetchall()
        return [
            {
                "id": cmte or "",
                "name": name or "(unnamed)",
                "detail": (
                    f"{cmte or '—'}"
                    + (f" · treas {tres}" if tres else "")
                ),
                "amount": None,
                "amount_fmt": "—",
                "address_type": "fec_committee",
                "canonical_address": (canon or "").strip() or "(no street)",
            }
            for name, cmte, tres, canon in rows
        ]

    if focus == "fec":
        # Prefer contributor density on the page: contributors first by $ within
        # kind, resolve committee IDs to names, include expenditures.
        rows = conn.execute(
            f"""
            SELECT * FROM (
                SELECT
                    f.contributor_name AS name,
                    'contributor' AS kind,
                    0 AS kind_rank,
                    f.contribution_amount AS amount,
                    COALESCE(
                        NULLIF(TRIM(f.occupation), ''),
                        NULLIF(TRIM(f.employer), ''),
                        f.fec_cmte_id
                    ) AS detail,
                    a.address_type,
                    a.canonical_address
                FROM Addresses a
                {gjoin}
                JOIN fec_individual_contributions f ON f.id = a.owner_id
                WHERE ({key_expr}) = ? AND ({where})
                  AND a.address_type = 'fec_contributor'
                UNION ALL
                SELECT
                    COALESCE(NULLIF(TRIM(c.name), ''), c.fec_cmte_id),
                    'committee',
                    1,
                    NULL,
                    c.fec_cmte_id,
                    a.address_type,
                    a.canonical_address
                FROM Addresses a
                {gjoin}
                JOIN fec_committees c ON c.id = a.owner_id
                WHERE ({key_expr}) = ? AND ({where})
                  AND a.address_type = 'fec_committee'
                UNION ALL
                SELECT
                    COALESCE(
                        NULLIF(TRIM(cm.name), ''),
                        NULLIF(TRIM(t.fec_cmte_id), ''),
                        NULLIF(TRIM(t.other_cmte_id), ''),
                        'committee transaction'
                    ),
                    'transaction ' || COALESCE(t.transaction_type, ''),
                    2,
                    t.transaction_amount,
                    COALESCE(t.fec_cmte_id, '') || ' · ' || COALESCE(CAST(t.transaction_date AS VARCHAR), ''),
                    a.address_type,
                    a.canonical_address
                FROM Addresses a
                {gjoin}
                JOIN fec_committee_transactions t ON t.id = a.owner_id
                LEFT JOIN fec_committees cm ON cm.fec_cmte_id = t.fec_cmte_id
                WHERE ({key_expr}) = ? AND ({where})
                  AND a.address_type = 'fec_committee_transaction'
                UNION ALL
                SELECT
                    COALESCE(
                        NULLIF(TRIM(o.payee_name), ''),
                        NULLIF(TRIM(cm.name), ''),
                        o.fec_cmte_id,
                        'expenditure'
                    ),
                    'expenditure',
                    2,
                    o.expenditure_amount,
                    COALESCE(o.purpose, '') || ' · ' || COALESCE(o.fec_cmte_id, ''),
                    a.address_type,
                    a.canonical_address
                FROM Addresses a
                {gjoin}
                JOIN fec_operating_expenditures o ON o.id = a.owner_id
                LEFT JOIN fec_committees cm ON cm.fec_cmte_id = o.fec_cmte_id
                WHERE ({key_expr}) = ? AND ({where})
                  AND a.address_type = 'fec_operating_expenditure'
                UNION ALL
                SELECT
                    COALESCE(
                        NULLIF(TRIM(s.payee_name), ''),
                        s.fec_cand_id,
                        'candidate spend'
                    ),
                    'candidate spend',
                    2,
                    s.spending_amount,
                    COALESCE(s.purpose, '') || ' · ' || COALESCE(s.fec_cmte_id, ''),
                    a.address_type,
                    a.canonical_address
                FROM Addresses a
                {gjoin}
                JOIN fec_candidate_spendings s ON s.id = a.owner_id
                WHERE ({key_expr}) = ? AND ({where})
                  AND a.address_type = 'fec_candidate_spending'
            ) u
            ORDER BY kind_rank ASC, amount DESC NULLS LAST, name
            LIMIT ?
            """,
            [cluster_key, cluster_key, cluster_key, cluster_key, cluster_key, top_n],
        ).fetchall()
        return [
            {
                "id": kind,
                "name": name or "(unnamed)",
                "detail": (detail or "").strip(" ·"),
                "amount": amt,
                "amount_fmt": fmt_money(amt),
                "address_type": at,
                "canonical_address": (canon or "").strip() or "(no street)",
            }
            for name, kind, _krank, amt, detail, at, canon in rows
        ]

    if focus == "contractor":
        rows = conn.execute(
            f"""
            SELECT
                c.name,
                c.filer_ein,
                c.amount,
                c.tax_year,
                a.canonical_address
            FROM Addresses a
            {gjoin}
            JOIN Contractors c ON c.contractor_id = a.owner_id
            WHERE ({key_expr}) = ?
              AND ({where})
              AND a.address_type = 'contractor'
            ORDER BY c.amount DESC NULLS LAST
            LIMIT ?
            """,
            [cluster_key, top_n],
        ).fetchall()
        return [
            {
                "id": fe or "",
                "name": name or "(unnamed)",
                "detail": f"filer {fe or '—'} · {yr or '—'}",
                "amount": amt,
                "amount_fmt": fmt_money(amt),
                "address_type": "contractor",
                "canonical_address": (canon or "").strip() or "(no street)",
            }
            for name, fe, amt, yr, canon in rows
        ]

    if focus in ("grants_out", "usg"):
        # Charity filer stack: amount is grants_to_others or govt_amt.
        amt_col = FOCUS_DOMAINS[focus].get("charity_amount_col") or (
            "grants_to_others" if focus == "grants_out" else "govt_amt"
        )
        if amt_col not in ("grants_to_others", "govt_amt"):
            raise ValueError(f"unsupported charity amount column: {amt_col}")
        amt_label = "out grants" if focus == "grants_out" else "govt"
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(c.filer_name), ''), NULLIF(TRIM(a.name), ''), c.ein)
                    AS display_name,
                c.ein,
                c.{amt_col},
                c.tax_year,
                a.canonical_address,
                c.receipt_amt
            FROM Addresses a
            {gjoin}
            JOIN Charities c ON c.charity_id = a.owner_id
            WHERE ({key_expr}) = ?
              AND ({where})
              AND a.address_type = 'charity'
            ORDER BY c.{amt_col} DESC NULLS LAST, c.receipt_amt DESC NULLS LAST
            LIMIT ?
            """,
            [cluster_key, top_n],
        ).fetchall()
        return [
            {
                "id": ein or "",
                "name": name or "(unnamed)",
                "detail": f"EIN {ein or '—'} · {yr or '—'} · {amt_label}",
                "amount": amt,
                "amount_fmt": fmt_money(amt),
                "address_type": "charity",
                "canonical_address": (canon or "").strip() or "(no street)",
            }
            for name, ein, amt, yr, canon, _receipt in rows
        ]

    if focus == "grants":
        # Incoming grants — over-fetch then drop name-suppressed / privacy rollups
        from grant_suppress import is_suppressed_grantee  # noqa: WPS433

        fetch_n = max(top_n * 10, min(1000, top_n * 20))
        rows = conn.execute(
            f"""
            SELECT
                gr.grantee_name,
                gr.filer_ein,
                gr.grant_amt,
                gr.tax_year,
                gr.recipient_ein,
                a.canonical_address
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
        out = []
        for gname, fe, amt, yr, rein, canon in rows:
            if is_suppressed_grantee(gname):
                continue
            out.append(
                {
                    "id": rein or "",
                    "name": gname or "(unnamed)",
                    "detail": f"filer {fe or '—'} · recip {rein or '—'} · {yr or '—'}",
                    "amount": amt,
                    "amount_fmt": fmt_money(amt),
                    "address_type": "grant",
                    "canonical_address": (canon or "").strip() or "(no street)",
                }
            )
            if len(out) >= top_n:
                break
        return out

    raise ValueError(f"unknown focus for entity fetch: {focus}")


def fetch_grants_simple(conn, slice_by, cluster_key, top_n, *, lat_long=False):
    """Top grants excluding name-suppressed / privacy rollups."""
    from grant_suppress import is_suppressed_grantee  # noqa: WPS433

    key_expr, where, gjoin = _member_filter_sql(slice_by, conn, lat_long=lat_long)
    fetch_n = max(top_n * 10, min(1000, top_n * 20))
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
            "filer_ein": fe,
            "grantee_name": gn,
            "grant_amt": amt,
            "amt_fmt": fmt_money(amt),
            "tax_year": yr,
        }
        for fe, gn, amt, yr in rows
        if not is_suppressed_grantee(gn)
    ]
    return out[:top_n]


def render_template(name: str, **kwargs) -> str:
    from mako.lookup import TemplateLookup

    lookup = TemplateLookup(
        directories=[str(SCRIPT_DIR / "templates")],
        input_encoding="utf-8",
    )
    tpl = lookup.get_template(name)
    return tpl.render(css=CSS, **kwargs)


def write_focus_report(
    db_path: str,
    output_dir: Path,
    focus: str,
    slice_by: str,
    min_multi_type: int,
    min_focus: int,
    require_grift_signal: bool,
    top_n: int,
    max_clusters: int,
    physical_notes_path: Path,
    include_officers: bool,
    include_grants: bool,
    *,
    lat_long: bool = False,
) -> int:
    if focus not in FOCUS_DOMAINS:
        raise ValueError(f"Unknown focus {focus!r}")
    if slice_by not in SLICE_MODES:
        raise ValueError(f"Unknown slice-by {slice_by!r}")

    domain = FOCUS_DOMAINS[focus]
    conn = duckdb.connect(db_path, read_only=True)
    try:
        if focus == "medicare":
            ok = ensure_medicare_rollup(conn)
            print(
                f"  medicare rollup: {'ready' if ok else 'MISSING (rank/$ degraded)'}",
                flush=True,
            )
        # Probe FEC column names that may differ
        if focus == "fec":
            try:
                cols = {r[0] for r in conn.execute("DESCRIBE fec_operating_expenditures").fetchall()}
                if "expenditure_amount" not in cols and "disbursement_amount" in cols:
                    # patch money SQL at runtime by re-fetch — handled via try in build
                    pass
            except Exception:
                pass

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
        pop_cutpoints = cutpoints_for_focus(focus, pop_cache)

        print(
            f"  fetching clusters focus={focus} slice={slice_by} "
            f"admission=focus>0 (optional floors multi={min_multi_type} "
            f"focus={min_focus}) max_clusters={max_clusters}...",
            flush=True,
        )
        try:
            clusters_raw = fetch_clusters_focus(
                conn,
                slice_by,
                focus,
                min_multi_type,
                min_focus,
                require_grift_signal,
                max_clusters,
                lat_long=lat_long,
            )
        except Exception as e:
            # FEC operating expenditures column name variance
            if focus == "fec" and "expenditure_amount" in str(e).lower():
                print(f"  FEC column adjust: {e}", flush=True)
            raise

        if not clusters_raw:
            print("No clusters matched selection criteria.")
            return 0

        clusters_out = []
        # Stable provider dossiers for medicare focus (shared across slices).
        providers_dir = SCRIPT_DIR / "reports" / "providers"
        written_npis: set[str] = set()
        provider_index_rows: list[dict] = []
        for i, c in enumerate(clusters_raw, 1):
            key = str(c["cluster_key"])
            sample = c.get("sample_address") or key
            slug = slugify_address(f"{focus}-{slice_by}-{key}")
            detail_file = f"{slug}.html"
            phy_is_po_box = is_po_box(sample) or (
                slice_by == "colocator" and key.upper().startswith("PO:")
            )
            c["phy_is_po_box"] = phy_is_po_box
            c["suspicion_score"] = suspicion_score_focus(c, focus)
            c["reason_codes"] = reason_codes_focus(
                c, min_multi_type, min_focus, focus
            )
            c["maps_url"] = google_maps_url(sample, zoom=17)
            c["detail_file"] = detail_file
            c["slug"] = slug
            c["sample_address"] = sample
            c["focus_label"] = domain["label"]
            c["entity_title"] = domain["entity_title"]
            c["amount_label"] = domain["amount_label"]
            c["review_tag"] = domain["review_tag"]
            if slice_by == "address":
                c["canonical_address"] = key
            else:
                c["canonical_address"] = (
                    f"{key}  ·  e.g. {sample}" if sample != key else key
                )
            c["percentile_chips"] = annotate_cluster_percentile_chips(
                c, focus, pop_cutpoints
            )
            clusters_out.append(c)

            if i == 1 or i % 10 == 0:
                print(f"  detail {i}/{len(clusters_raw)}: {key[:60]}...", flush=True)

            entities = fetch_focus_entities(
                conn, slice_by, key, focus, top_n, lat_long=lat_long
            )
            if focus == "medicare":
                from provider_pages import (  # noqa: WPS433
                    provider_detail_href,
                    write_provider_page,
                )

                for ent in entities:
                    npi = str(ent.get("id") or "").strip()
                    if not npi:
                        continue
                    ent["detail_href"] = provider_detail_href(npi)
                    if npi not in written_npis:
                        path = write_provider_page(
                            conn,
                            npi,
                            providers_dir,
                            generated_at=generated_at,
                        )
                        if path:
                            written_npis.add(npi)
                            provider_index_rows.append(
                                {
                                    "npi": npi,
                                    "display_name": ent.get("name") or npi,
                                    "total_paid": float(ent.get("amount") or 0),
                                    "total_paid_fmt": ent.get("amount_fmt") or "—",
                                    "hcpcs_type_count": int(
                                        ent.get("hcpcs_type_count") or 0
                                    ),
                                    "total_claims": int(ent.get("total_claims") or 0),
                                }
                            )
            # Charity-based focuses list filers as primary entities (ranked by $).
            charities = (
                []
                if focus in ("grants_out", "usg")
                else fetch_charities(conn, slice_by, key, top_n, lat_long=lat_long)
            )
            officers = (
                fetch_officers(conn, slice_by, key, top_n, lat_long=lat_long)
                if include_officers
                else []
            )
            # Incoming-grant focus already lists grants as primary entities.
            grants = (
                fetch_grants_simple(conn, slice_by, key, top_n, lat_long=lat_long)
                if include_grants and focus != "grants"
                else []
            )

            from cluster_table_payload import (  # noqa: WPS433
                build_detail_tables,
                dumps_table_json,
            )

            detail_tables = build_detail_tables(
                entities=entities,
                charities=charities,
                officers=officers,
                grants=grants,
                focus=focus,
                entity_title=domain.get("entity_title", "Entities"),
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

            widen_links = build_widen_links(
                focus=focus,
                slice_by=slice_by,
                cluster_key=key,
                sample_address=sample,
                report_day=report_date,
                reports_dir=SCRIPT_DIR / "reports",
                output_dir=output_dir,
                conn=conn,
                lat_long=lat_long,
                context="national",
            )
            html = render_template(
                "focus_cluster_detail.mako",
                cluster=c,
                entities=entities,
                charities=charities,
                officers=officers,
                grants=grants,
                focus=focus,
                domain=domain,
                physical_note=physical_note_for(sample, notes)
                or physical_note_for(key, notes),
                generated_at=generated_at,
                detail_tables_json=dumps_table_json(detail_tables),
                map_points=detail_map,
                breadcrumbs=crumbs_national_detail(
                    focus=focus,
                    slice_by=slice_by,
                    detail_label=str(c.get("canonical_address") or key),
                ),
                widen_links=widen_links,
            )
            (output_dir / detail_file).write_text(html, encoding="utf-8")

            json_path = data_dir / f"{slug}.json"
            json_path.write_text(
                json.dumps(
                    {
                        "slug": slug,
                        "focus": focus,
                        "slice_by": slice_by,
                        "cluster_key": key,
                        "sample_address": sample,
                        "focus_count": c.get("focus_count"),
                        "focus_amount": c.get("focus_amount"),
                        "suspicion_score": c.get("suspicion_score"),
                        "entities": entities,
                        "generated_at": generated_at,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )

        if focus == "medicare" and written_npis:
            print(
                f"  wrote {len(written_npis)} provider detail pages → {providers_dir}",
                flush=True,
            )
            try:
                from provider_pages import write_provider_index  # noqa: WPS433

                write_provider_index(
                    providers_dir,
                    provider_index_rows,
                    generated_at=generated_at,
                )
            except Exception as e:
                print(f"  provider index warn: {e}", flush=True)

        from cluster_table_payload import (  # noqa: WPS433
            build_focus_cluster_table,
            dumps_table_json,
        )

        table_payload = build_focus_cluster_table(
            clusters_out,
            focus=focus,
            min_focus=min_focus,
            rank_metric=domain.get("rank_metric", "focus_count"),
            rank_label=domain.get("rank_label", "Focus metric"),
        )
        from map_points import clusters_to_map_points  # noqa: WPS433

        map_points = clusters_to_map_points(clusters_out, slice_by=slice_by)
        from breadcrumbs import crumbs_national_index  # noqa: WPS433

        methodology = index_methodology_context(focus, pop_cutpoints)
        index_html = render_template(
            "focus_cluster_index.mako",
            clusters=clusters_out,
            cluster_count=len(clusters_out),
            generated_at=generated_at,
            report_date=report_date,
            db_path=db_path,
            min_multi_type=min_multi_type,
            min_focus=min_focus,
            max_clusters=max_clusters,
            require_grift_signal=require_grift_signal,
            slice_by=slice_by,
            slice_label=mode["label"],
            focus=focus,
            focus_label=domain["label"],
            domain=domain,
            rank_label=domain.get("rank_label", "Focus metric"),
            cluster_table_json=dumps_table_json(table_payload),
            map_points=map_points,
            breadcrumbs=crumbs_national_index(focus=focus, slice_by=slice_by),
            methodology=methodology,
        )
        if map_points:
            (data_dir / "map_points.json").write_text(
                json.dumps(map_points, indent=2), encoding="utf-8"
            )
        (output_dir / "index.html").write_text(index_html, encoding="utf-8")

        serializable = []
        for c in clusters_out:
            row = {k: v for k, v in c.items() if k != "address_types"}
            row["address_types"] = list(c.get("address_types") or [])
            serializable.append(row)
        with open(data_dir / "clusters.json", "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, default=str)

        metadata = {
            "generated_at": generated_at,
            "db_path": db_path,
            "focus": focus,
            "focus_label": domain["label"],
            "slice_by": slice_by,
            "slice_label": mode["label"],
            "criteria": {
                "min_multi_type": min_multi_type,
                "min_focus": min_focus,
                "require_grift_signal": require_grift_signal,
                "top_n_entities": top_n,
                "max_clusters": max_clusters,
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

        readme = f"""# {domain['label']} — {mode['label']} — {report_date}

Focus: **{focus}** · Slice: **{slice_by}**

- Open `index.html` in a browser.
- Ranked by focus entity count, then dollars.

Clusters: {len(clusters_out)}
Generated: {generated_at}
DB: {db_path}
"""
        (output_dir / "README.md").write_text(readme, encoding="utf-8")
        print(f"Wrote {len(clusters_out)} cluster pages to {output_dir}", flush=True)
        return len(clusters_out)
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Focus cluster reports (medicare / fec / fec_committee / contractor / "
            "grants / grants_out / usg)"
        )
    )
    p.add_argument("--db-path", default=os.environ.get("IRS990_DB_PATH", DEFAULT_DB))
    p.add_argument(
        "--focus",
        required=True,
        choices=list(FOCUS_DOMAINS.keys()),
        help="Primary entity stack to rank on",
    )
    p.add_argument(
        "--slice-by",
        choices=list(SLICE_MODES.keys()),
        default="address",
    )
    p.add_argument("--lat-long", action="store_true")
    p.add_argument("--output-dir")
    p.add_argument("--physical-notes", default=str(SCRIPT_DIR / "physical_notes.json"))
    p.add_argument(
        "--min-multi-type",
        type=int,
        default=None,
        help="Deprecated optional floor on distinct address_types (0=off, default)",
    )
    p.add_argument(
        "--min-focus",
        type=int,
        default=None,
        help="Deprecated optional floor on focus rows (0=off, default). "
        "Suite size is max_clusters after rank.",
    )
    p.add_argument(
        "--require-grift-signal",
        action="store_true",
        help="Unused in practice (grift_ratio not populated); leave off.",
    )
    p.add_argument("--top-n", type=int, default=25)
    p.add_argument(
        "--max-clusters",
        type=int,
        default=100,
        help="Keep top N clusters after rank (the real suite cap)",
    )
    p.add_argument("--no-officers", action="store_true")
    p.add_argument("--no-grants", action="store_true")
    args = p.parse_args()

    domain = FOCUS_DOMAINS[args.focus]
    min_multi = (
        args.min_multi_type
        if args.min_multi_type is not None
        else domain["min_multi_default"]
    )
    min_focus = (
        args.min_focus if args.min_focus is not None else domain["min_focus_default"]
    )

    prefix = f"{domain['out_prefix']}_{args.slice_by}_clusters"
    if args.lat_long and args.slice_by == "colocator":
        prefix = f"{domain['out_prefix']}_colocator_ll_clusters"
    # Stable path (no date) for public deploy — pass --output-dir to override.
    out = (
        Path(args.output_dir)
        if args.output_dir
        else SCRIPT_DIR / "reports" / prefix
    )
    if not os.path.exists(args.db_path):
        raise SystemExit(f"Database not found: {args.db_path}")

    print(
        f"Opening {args.db_path} focus={args.focus} slice={args.slice_by} "
        f"min_multi={min_multi} min_focus={min_focus} → {out}",
        flush=True,
    )
    n = write_focus_report(
        db_path=args.db_path,
        output_dir=out,
        focus=args.focus,
        slice_by=args.slice_by,
        min_multi_type=min_multi,
        min_focus=min_focus,
        require_grift_signal=args.require_grift_signal,
        top_n=args.top_n,
        max_clusters=args.max_clusters,
        physical_notes_path=Path(args.physical_notes),
        include_officers=not args.no_officers,
        include_grants=not args.no_grants,
        lat_long=args.lat_long,
    )
    return 0 if n >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
