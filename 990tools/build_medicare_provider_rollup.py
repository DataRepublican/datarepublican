#!/usr/bin/env python3
"""Build consolidated Medicare provider tables from line-level spending.

Source: medicare_provider_spending (~230M rows, HCPCS × month grain)
Outputs:
  medicare_provider_hcpcs  — one row per (billing NPI, HCPCS code): type/$ detail
  medicare_provider_rollup — one row per billing NPI: counts, type count, $

Most providers bill a short list of HCPCS types (median ~4). Rollups make
cluster ranking by $ cheap and detail pages can show type/$ without scanning
230M rows.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import duckdb

DEFAULT_DB = os.environ.get("IRS990_DB_PATH", "/Volumes/Data/final/irs990.duckdb")
DEFAULT_SIDE = os.environ.get(
    "MEDICARE_ROLLUP_DB",
    "/Volumes/Data/final/medicare_provider_rollup.duckdb",
)


def hcpcs_sql(src: str) -> str:
    return f"""
CREATE OR REPLACE TABLE medicare_provider_hcpcs AS
SELECT
    billing_provider_npi AS npi,
    COALESCE(NULLIF(TRIM(hcpcs_code), ''), '—') AS hcpcs_code,
    COUNT(*)::BIGINT AS spend_rows,
    SUM(COALESCE(total_claims, 0))::BIGINT AS total_claims,
    SUM(COALESCE(total_unique_beneficiaries, 0))::BIGINT AS total_beneficiaries,
    SUM(COALESCE(total_paid, 0))::DOUBLE AS total_paid,
    MIN(claim_from_month) AS first_month,
    MAX(claim_from_month) AS last_month
FROM {src}.medicare_provider_spending
WHERE billing_provider_npi IS NOT NULL
  AND TRIM(billing_provider_npi) != ''
GROUP BY 1, 2
"""


def rollup_sql(src: str) -> str:
    return f"""
CREATE OR REPLACE TABLE medicare_provider_rollup AS
SELECT
    h.npi,
    COUNT(*)::BIGINT AS hcpcs_type_count,
    SUM(h.spend_rows)::BIGINT AS spend_rows,
    SUM(h.total_claims)::BIGINT AS total_claims,
    SUM(h.total_beneficiaries)::BIGINT AS total_beneficiaries,
    SUM(h.total_paid)::DOUBLE AS total_paid,
    MIN(h.first_month) AS first_month,
    MAX(h.last_month) AS last_month,
    ARG_MAX(h.hcpcs_code, h.total_paid) AS top_hcpcs_code,
    MAX(h.total_paid)::DOUBLE AS top_hcpcs_paid,
    ANY_VALUE(m.id) AS provider_id,
    ANY_VALUE(m.organization_name) AS organization_name,
    ANY_VALUE(
        TRIM(COALESCE(m.provider_first_name, '') || ' ' || COALESCE(m.provider_last_name, ''))
    ) AS person_name,
    ANY_VALUE(m.entity_type_code) AS entity_type_code
FROM medicare_provider_hcpcs h
LEFT JOIN {src}.medicare_providers m ON m.npi = h.npi
GROUP BY h.npi
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db-path", default=DEFAULT_DB, help="Source IRS990 DB (read)")
    p.add_argument(
        "--side-db",
        default=DEFAULT_SIDE,
        help="Writable DB for rollup tables (default: sidecars next to main). "
        "Use same path as --db-path to write in-place when unlocked.",
    )
    p.add_argument(
        "--in-place",
        action="store_true",
        help="Write tables into --db-path (requires exclusive lock)",
    )
    p.add_argument(
        "--memory-limit",
        default=os.environ.get("DUCKDB_MEMORY_LIMIT", "16GB"),
    )
    p.add_argument("--threads", type=int, default=int(os.environ.get("DUCKDB_THREADS", "4")))
    args = p.parse_args()

    if not os.path.exists(args.db_path):
        print(f"DB not found: {args.db_path}", file=sys.stderr)
        return 1

    cfg = {"memory_limit": args.memory_limit, "threads": str(args.threads)}
    t0 = time.time()

    if args.in_place or os.path.abspath(args.side_db) == os.path.abspath(args.db_path):
        print(f"Opening {args.db_path} (write, in-place)…", flush=True)
        try:
            con = duckdb.connect(args.db_path, config=cfg)
        except Exception as e:
            print(f"In-place open failed: {e}", file=sys.stderr)
            print("Retry with side DB (omit --in-place).", file=sys.stderr)
            return 1
        src = "main"  # tables live in default schema
        # When in-place, FROM medicare_provider_spending (no alias)
        h_sql = hcpcs_sql("main").replace("main.medicare_provider_spending", "medicare_provider_spending")
        # Actually main. might not work — use bare names for in-place
        h_sql = """
CREATE OR REPLACE TABLE medicare_provider_hcpcs AS
SELECT
    billing_provider_npi AS npi,
    COALESCE(NULLIF(TRIM(hcpcs_code), ''), '—') AS hcpcs_code,
    COUNT(*)::BIGINT AS spend_rows,
    SUM(COALESCE(total_claims, 0))::BIGINT AS total_claims,
    SUM(COALESCE(total_unique_beneficiaries, 0))::BIGINT AS total_beneficiaries,
    SUM(COALESCE(total_paid, 0))::DOUBLE AS total_paid,
    MIN(claim_from_month) AS first_month,
    MAX(claim_from_month) AS last_month
FROM medicare_provider_spending
WHERE billing_provider_npi IS NOT NULL AND TRIM(billing_provider_npi) != ''
GROUP BY 1, 2
"""
        r_sql = """
CREATE OR REPLACE TABLE medicare_provider_rollup AS
SELECT
    h.npi,
    COUNT(*)::BIGINT AS hcpcs_type_count,
    SUM(h.spend_rows)::BIGINT AS spend_rows,
    SUM(h.total_claims)::BIGINT AS total_claims,
    SUM(h.total_beneficiaries)::BIGINT AS total_beneficiaries,
    SUM(h.total_paid)::DOUBLE AS total_paid,
    MIN(h.first_month) AS first_month,
    MAX(h.last_month) AS last_month,
    ARG_MAX(h.hcpcs_code, h.total_paid) AS top_hcpcs_code,
    MAX(h.total_paid)::DOUBLE AS top_hcpcs_paid,
    ANY_VALUE(m.id) AS provider_id,
    ANY_VALUE(m.organization_name) AS organization_name,
    ANY_VALUE(
        TRIM(COALESCE(m.provider_first_name, '') || ' ' || COALESCE(m.provider_last_name, ''))
    ) AS person_name,
    ANY_VALUE(m.entity_type_code) AS entity_type_code
FROM medicare_provider_hcpcs h
LEFT JOIN medicare_providers m ON m.npi = h.npi
GROUP BY h.npi
"""
        try:
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] "
                "Building medicare_provider_hcpcs…",
                flush=True,
            )
            con.execute(h_sql)
            n_h = con.execute("SELECT COUNT(*) FROM medicare_provider_hcpcs").fetchone()[0]
            print(f"  hcpcs rows={n_h:,} ({time.time()-t0:.1f}s)", flush=True)
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] "
                "Building medicare_provider_rollup…",
                flush=True,
            )
            con.execute(r_sql)
            _index_and_stats(con, time.time() - t0)
            return 0
        finally:
            con.close()

    # Side DB: ATTACH source read-only, write rollups locally
    side = args.side_db
    os.makedirs(os.path.dirname(side) or ".", exist_ok=True)
    print(f"Opening side DB {side} (write)…", flush=True)
    print(f"  ATTACH source {args.db_path} READ_ONLY as src", flush=True)
    con = duckdb.connect(side, config=cfg)
    try:
        # Detach if re-run
        try:
            con.execute("DETACH src")
        except Exception:
            pass
        con.execute(f"ATTACH '{args.db_path}' AS src (READ_ONLY)")
        print(
            f"[{datetime.now().isoformat(timespec='seconds')}] "
            "Building medicare_provider_hcpcs from src…",
            flush=True,
        )
        con.execute(hcpcs_sql("src"))
        n_h = con.execute("SELECT COUNT(*) FROM medicare_provider_hcpcs").fetchone()[0]
        n_npi = con.execute(
            "SELECT COUNT(DISTINCT npi) FROM medicare_provider_hcpcs"
        ).fetchone()[0]
        print(
            f"  hcpcs rows={n_h:,} distinct_npi={n_npi:,} ({time.time()-t0:.1f}s)",
            flush=True,
        )
        print(
            f"[{datetime.now().isoformat(timespec='seconds')}] "
            "Building medicare_provider_rollup…",
            flush=True,
        )
        con.execute(rollup_sql("src"))
        _index_and_stats(con, time.time() - t0)
        print(
            f"Side DB ready: {side}\n"
            "Report generators will ATTACH this when main lacks rollup tables.\n"
            "When main is unlocked: "
            f"python3 build_medicare_provider_rollup.py --in-place --db-path {args.db_path}",
            flush=True,
        )
        return 0
    finally:
        con.close()


def _index_and_stats(con: duckdb.DuckDBPyConnection, elapsed: float) -> None:
    n_r = con.execute("SELECT COUNT(*) FROM medicare_provider_rollup").fetchone()[0]
    stats = con.execute(
        """
        SELECT
            SUM(total_paid),
            approx_quantile(hcpcs_type_count, 0.5),
            approx_quantile(hcpcs_type_count, 0.9),
            approx_quantile(total_paid, 0.5),
            approx_quantile(total_paid, 0.9)
        FROM medicare_provider_rollup
        """
    ).fetchone()
    print(f"  rollup rows={n_r:,}", flush=True)
    print(
        f"  sum_paid=${stats[0]:,.0f}  "
        f"median_types={stats[1]} p90_types={stats[2]}  "
        f"median_paid=${stats[3]:,.0f} p90_paid=${stats[4]:,.0f}",
        flush=True,
    )
    print("Creating indexes…", flush=True)
    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_medicare_provider_hcpcs_npi ON medicare_provider_hcpcs(npi)",
        "CREATE INDEX IF NOT EXISTS idx_medicare_provider_hcpcs_code ON medicare_provider_hcpcs(hcpcs_code)",
        "CREATE INDEX IF NOT EXISTS idx_medicare_provider_rollup_npi ON medicare_provider_rollup(npi)",
        "CREATE INDEX IF NOT EXISTS idx_medicare_provider_rollup_paid ON medicare_provider_rollup(total_paid)",
        "CREATE INDEX IF NOT EXISTS idx_medicare_provider_rollup_provider_id ON medicare_provider_rollup(provider_id)",
    ):
        try:
            con.execute(sql)
        except Exception as e:
            print(f"  index note: {e}", flush=True)
    print(f"Done in {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
