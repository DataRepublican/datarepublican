#!/usr/bin/env python3
"""Write gin_phonebook_100m_pairs.tsv (ghost name → suggested EIN, ≥ $100M)."""

from pathlib import Path
import duckdb

DB = Path(__file__).resolve().parent / "irs990.duckdb"
OUT = Path(__file__).resolve().parent / "gin_phonebook_100m_pairs.tsv"

SQL = r"""
COPY (
  WITH latest AS (
    SELECT ein, filer_name,
           ROW_NUMBER() OVER (PARTITION BY ein ORDER BY tax_year DESC NULLS LAST) AS rn
    FROM Charities
    WHERE filer_name IS NOT NULL AND TRIM(filer_name) != ''
  ),
  pairs AS (
    SELECT
      g.recipient_ein AS gin,
      g.recipient_ein_backfilled AS suggested_ein,
      ANY_VALUE(g.grantee_name) AS ghost_name,
      SUM(g.grant_amt) AS dollars,
      COUNT(*)::BIGINT AS grant_rows
    FROM Grants g
    WHERE g.recipient_ein LIKE '70%'
      AND regexp_matches(COALESCE(g.recipient_ein_backfilled, ''), '^[0-9]{9}$')
    GROUP BY g.recipient_ein, g.recipient_ein_backfilled
    HAVING SUM(g.grant_amt) >= 100000000
  )
  SELECT
    p.dollars,
    p.grant_rows,
    p.ghost_name,
    p.suggested_ein,
    l.filer_name AS suggested_name,
    p.gin
  FROM pairs p
  LEFT JOIN latest l ON l.ein = p.suggested_ein AND l.rn = 1
  ORDER BY p.dollars DESC
) TO '__OUT__' (HEADER, DELIMITER '\t')
"""


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    con.execute(SQL.replace("__OUT__", str(OUT)))
    print(f"Wrote {OUT} lines={sum(1 for _ in OUT.open())}")


if __name__ == "__main__":
    main()
