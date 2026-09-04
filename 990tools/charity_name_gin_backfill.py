#!/usr/bin/env python3
"""Fill Grants.recipient_ein_backfilled from Charity name-history GINs.

990-PF grants often only have a name. Match stored a GIN in recipient_ein
(70 + SHA256 of suffix-stripped name; 66- or 130-char forms). This maps
unambiguous Charity.filer_name history through the same hash and writes
the EIN into recipient_ein_backfilled only. Does not touch recipient_ein.

Why: Trust→Foundation 2024 used grantee_name GATES FOUNDATION after the
divorce rename; the 2024 Charity row for 562618866 already has that name.

Usage:
  python charity_name_gin_backfill.py --db-path irs990.duckdb          # dry-run
  python charity_name_gin_backfill.py --db-path irs990.duckdb --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

SQL_DIR = Path(__file__).resolve().parent
SETUP_SQL = (SQL_DIR / "charity_name_gin_backfill.sql").read_text()
DEFAULT_DB = SQL_DIR / "irs990.duckdb"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    p.add_argument(
        "--apply",
        action="store_true",
        help="Write recipient_ein_backfilled. Default is dry-run.",
    )
    args = p.parse_args()
    db = args.db_path.expanduser().resolve()
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1

    read_only = not args.apply
    con = duckdb.connect(str(db), read_only=read_only)
    print(f"DB {db} read_only={read_only}")
    con.execute(SETUP_SQL)
    n_keys = con.execute("SELECT COUNT(*) FROM gin_unique").fetchone()[0]
    print(f"Unambiguous Charity-GIN keys: {n_keys:,}")

    would = con.execute(
        """
        SELECT COUNT(*) FROM Grants g
        JOIN gin_unique u ON g.recipient_ein = u.gin
        WHERE g.recipient_ein LIKE '70%'
          AND (g.recipient_ein_backfilled IS NULL
               OR TRIM(g.recipient_ein_backfilled) = '')
        """
    ).fetchone()[0]
    print(f"GIN grant rows with empty backfill that match: {would:,}")

    gates = con.execute(
        """
        SELECT g.tax_year, g.grantee_name, g.recipient_ein_backfilled, u.ein
        FROM Grants g
        JOIN gin_unique u ON g.recipient_ein = u.gin
        WHERE g.filer_ein = '911663695'
          AND g.grantee_name ILIKE '%GATES%FOUNDATION%'
        ORDER BY g.tax_year DESC
        LIMIT 8
        """
    ).fetchall()
    print("Gates Trust → Foundation (sample):")
    for row in gates:
        print(f"  {row}")

    if not args.apply:
        print("Dry-run. Pass --apply to UPDATE recipient_ein_backfilled.")
        return 0

    con.execute(
        """
        UPDATE Grants g
        SET recipient_ein_backfilled = u.ein
        FROM gin_unique u
        WHERE g.recipient_ein = u.gin
          AND g.recipient_ein LIKE '70%'
          AND (g.recipient_ein_backfilled IS NULL
               OR TRIM(g.recipient_ein_backfilled) = '')
        """
    )
    filled = con.execute(
        """
        SELECT COUNT(*) FROM Grants g
        JOIN gin_unique u ON g.recipient_ein = u.gin
        WHERE g.recipient_ein LIKE '70%'
          AND g.recipient_ein_backfilled = u.ein
        """
    ).fetchone()[0]
    try:
        con.execute("CHECKPOINT")
    except Exception:
        pass
    print(f"Applied. GIN rows now backfilled via Charity-GIN: {filled:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
