#!/usr/bin/env python3
"""Correct Grants.recipient_ein_backfilled on GIN rows using the repaired phonebook.

Does not touch recipient_ein. Targets only GIN keys (70…) with a 9-digit backfill.

1. Re-resolve the grantee name (DAF allowlist + exact-core cream with legal suffixes
   and namesake dominance).
2. Else 1-edit EIN repair if the BMF name overlaps the ghost.
3. Else keep if the current EIN still exists and its official name is a core of the ghost
   (Charity-GIN / rename cases like BILL & MELINDA → GATES FOUNDATION).
4. Else clear (stay a ghost). Missing BMF/Charity EINs always clear unless repaired.

Usage:
  python repair_phonebook_backfill.py --db-path irs990.duckdb
  python repair_phonebook_backfill.py --db-path irs990.duckdb --apply
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from bmf_fuzzy_candidate_matcher import (
    build_exact_core_phonebook,
    get_phonebook_sig_seq,
    is_generic_grantee,
    repair_ein_typo,
    resolve_phonebook_name,
)

DEFAULT_DB = Path(__file__).resolve().parent / "irs990.duckdb"


def _ghost_agrees(ghost: str, ein: str, names_by_ein: dict[str, list[str]]) -> bool:
    gseq = get_phonebook_sig_seq(ghost)
    if len(gseq) < 2:
        return False
    for official in names_by_ein.get(ein, []):
        oseq = get_phonebook_sig_seq(official)
        if not oseq:
            continue
        if gseq == oseq:
            return True
        if len(gseq) >= len(oseq) >= 2 and (
            gseq[-len(oseq) :] == oseq or gseq[: len(oseq)] == oseq
        ):
            return True
        if len(oseq) >= len(gseq) >= 2 and (
            oseq[-len(gseq) :] == gseq or oseq[: len(gseq)] == gseq
        ):
            return True
    return False


def decide(
    name: str,
    current: str,
    book: dict,
    bmf_by_ein: dict,
    names_by_ein: dict[str, list[str]],
) -> tuple[str, str]:
    """Return (action, new_ein) where new_ein is '' to clear."""
    current = (current or "").strip()
    if is_generic_grantee(name):
        return "clear_generic", ""
    new = resolve_phonebook_name(name, book)
    if new and new == current:
        return "keep", current
    if new:
        return "reassign", new
    repaired = repair_ein_typo(current, name, bmf_by_ein)
    if repaired:
        return "repair_typo", repaired
    if current not in bmf_by_ein:
        return "clear_missing_ein", ""
    if _ghost_agrees(name, current, names_by_ein):
        return "keep", current
    return "clear_mismatch", ""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    db = args.db_path.expanduser().resolve()
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1

    con = duckdb.connect(str(db), read_only=not args.apply)
    print(f"DB {db} read_only={not args.apply}", flush=True)

    print("Loading BMF…", flush=True)
    bmf_rows = con.execute(
        "SELECT EIN, NAME, ASSET_CD FROM BMF WHERE EIN IS NOT NULL AND NAME IS NOT NULL"
    ).fetchall()
    print(f"  BMF {len(bmf_rows):,}", flush=True)
    print("Loading Charity name variants…", flush=True)
    char_rows = con.execute(
        """
        SELECT ein, filer_name, -1
        FROM (
          SELECT ein, filer_name,
                 ROW_NUMBER() OVER (
                   PARTITION BY ein, filer_name ORDER BY tax_year DESC NULLS LAST
                 ) AS rn
          FROM Charities
          WHERE ein IS NOT NULL AND TRIM(ein) != ''
            AND filer_name IS NOT NULL AND TRIM(filer_name) != ''
        )
        WHERE rn = 1
        """
    ).fetchall()
    print(f"  Charity variants {len(char_rows):,}", flush=True)

    recs = [{"ein": r[0], "name": r[1], "asset_cd": r[2]} for r in bmf_rows]
    variants = [{"ein": r[0], "name": r[1], "asset_cd": r[2]} for r in char_rows]
    print(f"BMF names {len(recs):,}; Charity name variants {len(variants):,}", flush=True)
    print("Building phonebook…", flush=True)
    book = build_exact_core_phonebook(recs, variants)
    print(f"Phonebook sigs {len(book):,}", flush=True)

    bmf_by_ein: dict = {}
    names_by_ein: dict[str, list[str]] = defaultdict(list)
    for r in recs + variants:
        ein, nm = r["ein"], r["name"]
        if ein not in bmf_by_ein:
            bmf_by_ein[ein] = r
        names_by_ein[ein].append(nm)

    print("Loading GIN+backfill pairs…", flush=True)
    pairs = con.execute(
        """
        SELECT
          g.grantee_name,
          g.recipient_ein_backfilled AS ein,
          COUNT(*)::BIGINT AS n,
          SUM(g.grant_amt)::DOUBLE AS dollars
        FROM Grants g
        WHERE g.recipient_ein LIKE '70%'
          AND length(g.recipient_ein_backfilled) = 9
        GROUP BY 1, 2
        """
    ).fetchall()
    print(f"GIN+backfill name/EIN pairs: {len(pairs):,}", flush=True)

    actions: list[tuple] = []
    counts: Counter = Counter()
    dollars: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    for name, ein, n, dol in pairs:
        action, new_ein = decide(name, ein, book, bmf_by_ein, names_by_ein)
        counts[action] += 1
        dollars[action] += dol or 0
        if action != "keep":
            actions.append((name, ein, new_ein, action))
            if len(samples[action]) < 8:
                samples[action].append((dol or 0, name, ein, new_ein))

    print("\nActions (distinct name/EIN pairs):")
    for k, v in counts.most_common():
        print(f"  {k:20} {v:8,}   ${dollars[k]:,.0f}")
    for act, rows in samples.items():
        print(f"\n  sample {act}:")
        for dol, name, old, new in sorted(rows, reverse=True)[:5]:
            print(f"    ${dol/1e6:10.1f}M  {name[:48]!r}\n      {old} -> {new or '(clear)'}")

    if not args.apply:
        print("\nDry-run. Pass --apply to UPDATE recipient_ein_backfilled on GIN rows.")
        return 0

    con.execute("DROP TABLE IF EXISTS phonebook_repair")
    con.execute(
        """
        CREATE TEMP TABLE phonebook_repair (
            grantee_name VARCHAR,
            old_ein VARCHAR,
            new_ein VARCHAR,
            action VARCHAR
        )
        """
    )
    con.executemany(
        "INSERT INTO phonebook_repair VALUES (?, ?, ?, ?)",
        actions,
    )
    before = con.execute(
        """
        SELECT COUNT(*) FROM Grants g
        JOIN phonebook_repair r
          ON g.grantee_name = r.grantee_name
         AND g.recipient_ein_backfilled = r.old_ein
        WHERE g.recipient_ein LIKE '70%'
        """
    ).fetchone()[0]
    con.execute(
        """
        UPDATE Grants g
        SET recipient_ein_backfilled = CASE
            WHEN r.new_ein IS NULL OR r.new_ein = '' THEN NULL
            ELSE r.new_ein
        END
        FROM phonebook_repair r
        WHERE g.grantee_name = r.grantee_name
          AND g.recipient_ein_backfilled = r.old_ein
          AND g.recipient_ein LIKE '70%'
        """
    )
    try:
        con.execute("CHECKPOINT")
    except Exception:
        pass
    print(f"Applied. Grant rows touched: {before:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
