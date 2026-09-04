#!/usr/bin/env python3
"""Backfill Addresses.owner_id for contractor rows (historical parse bug).

Root cause: Contractor.build_address() set owner_id from contractor_id only when
already assigned. At XML parse time contractor_id was still None, so every
contractor address landed with owner_id NULL. New parses use Contractor.id
(same pattern as Grant/Officer).

Strategy (covers all null-owner contractor Addresses in production tests):
  1) Pair by upper(name) + colocator when both sides have colocator (PO boxes).
  2) Remaining: pair by upper(name) with row_number within name among
     unmatched addresses / contractors.

Also copies colocator from Addresses → Contractors when contractor.colocator
is empty and owner_id is set (enables later geocode back-prop).

Usage:
  python3 scripts/backfill_contractor_owner_id.py
  python3 scripts/backfill_contractor_owner_id.py --db /Volumes/Data/final/irs990.duckdb
  python3 scripts/backfill_contractor_owner_id.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb"


def counts(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    n_addr = conn.execute(
        "SELECT COUNT(*) FROM Addresses WHERE address_type = 'contractor'"
    ).fetchone()[0]
    n_null = conn.execute(
        """
        SELECT COUNT(*) FROM Addresses
        WHERE address_type = 'contractor' AND owner_id IS NULL
        """
    ).fetchone()[0]
    n_join = conn.execute(
        """
        SELECT COUNT(*) FROM Addresses a
        INNER JOIN Contractors c ON c.contractor_id = a.owner_id
        WHERE a.address_type = 'contractor'
        """
    ).fetchone()[0]
    return {"addr": int(n_addr), "null_owner": int(n_null), "joinable": int(n_join)}


def backfill(conn: duckdb.DuckDBPyConnection, *, dry_run: bool) -> None:
    before = counts(conn)
    print(f"Before: {before}", flush=True)

    # Staging pairs: address_id → contractor_id
    conn.execute("DROP TABLE IF EXISTS _contractor_owner_pairs")
    conn.execute(
        """
        CREATE TEMP TABLE _contractor_owner_pairs AS
        WITH po_match AS (
            SELECT a.address_id, c.contractor_id
            FROM (
                SELECT
                    address_id,
                    upper(trim(name)) AS n,
                    colocator AS ck,
                    ROW_NUMBER() OVER (
                        PARTITION BY upper(trim(name)), colocator
                        ORDER BY address_id
                    ) AS rn
                FROM Addresses
                WHERE address_type = 'contractor'
                  AND owner_id IS NULL
                  AND colocator IS NOT NULL
                  AND trim(colocator) <> ''
                  AND name IS NOT NULL
                  AND trim(name) <> ''
            ) a
            INNER JOIN (
                SELECT
                    contractor_id,
                    upper(trim(name)) AS n,
                    colocator AS ck,
                    ROW_NUMBER() OVER (
                        PARTITION BY upper(trim(name)), colocator
                        ORDER BY contractor_id
                    ) AS rn
                FROM Contractors
                WHERE colocator IS NOT NULL
                  AND trim(colocator) <> ''
                  AND name IS NOT NULL
                  AND trim(name) <> ''
            ) c ON a.n = c.n AND a.ck = c.ck AND a.rn = c.rn
        ),
        used_c AS (SELECT contractor_id FROM po_match),
        used_a AS (SELECT address_id FROM po_match),
        name_match AS (
            SELECT a.address_id, c.contractor_id
            FROM (
                SELECT
                    address_id,
                    upper(trim(name)) AS n,
                    ROW_NUMBER() OVER (
                        PARTITION BY upper(trim(name))
                        ORDER BY address_id
                    ) AS rn
                FROM Addresses
                WHERE address_type = 'contractor'
                  AND owner_id IS NULL
                  AND address_id NOT IN (SELECT address_id FROM used_a)
                  AND name IS NOT NULL
                  AND trim(name) <> ''
            ) a
            INNER JOIN (
                SELECT
                    contractor_id,
                    upper(trim(name)) AS n,
                    ROW_NUMBER() OVER (
                        PARTITION BY upper(trim(name))
                        ORDER BY contractor_id
                    ) AS rn
                FROM Contractors
                WHERE contractor_id NOT IN (SELECT contractor_id FROM used_c)
                  AND name IS NOT NULL
                  AND trim(name) <> ''
            ) c ON a.n = c.n AND a.rn = c.rn
        )
        SELECT * FROM po_match
        UNION ALL
        SELECT * FROM name_match
        """
    )
    n_pairs = conn.execute("SELECT COUNT(*) FROM _contractor_owner_pairs").fetchone()[0]
    print(f"Paired rows ready to write: {n_pairs:,}", flush=True)

    if dry_run:
        print("Dry run — no UPDATE.", flush=True)
        return

    conn.execute(
        """
        UPDATE Addresses a
        SET owner_id = p.contractor_id
        FROM _contractor_owner_pairs p
        WHERE a.address_id = p.address_id
          AND a.address_type = 'contractor'
          AND a.owner_id IS NULL
        """
    )

    # Propagate colocator onto contractors when still empty
    conn.execute(
        """
        UPDATE Contractors c
        SET colocator = sub.colocator
        FROM (
            SELECT
                a.owner_id AS contractor_id,
                ANY_VALUE(a.colocator) AS colocator
            FROM Addresses a
            WHERE a.address_type = 'contractor'
              AND a.owner_id IS NOT NULL
              AND a.colocator IS NOT NULL
              AND trim(a.colocator) <> ''
            GROUP BY a.owner_id
        ) sub
        WHERE c.contractor_id = sub.contractor_id
          AND (c.colocator IS NULL OR trim(c.colocator) = '')
        """
    )

    after = counts(conn)
    print(f"After:  {after}", flush=True)
    print(
        f"Null owner remaining: {after['null_owner']:,} "
        f"(was {before['null_owner']:,}); joinable {after['joinable']:,}",
        flush=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB, help="DuckDB path")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Build pair counts only; do not UPDATE",
    )
    args = ap.parse_args()
    db = Path(args.db)
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1

    # Writer connection
    conn = duckdb.connect(str(db))
    try:
        backfill(conn, dry_run=args.dry_run)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
