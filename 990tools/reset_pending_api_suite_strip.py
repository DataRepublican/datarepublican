#!/usr/bin/env python3
"""Reset pending_api rows that benefit from census_strip suite removal back to pending."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import duckdb

from constants import DEFAULT_FINAL_DIR, GEOCODING_STATUS_PENDING_API


def _load_strip_regexes() -> list[re.Pattern]:
    path = Path(__file__).with_name("geocoding_patterns.json")
    regexes: list[str] = []
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for pattern in data.get("patterns", []):
        if pattern.get("name") != "census_strip_suites":
            continue
        for sub in pattern.get("patterns", []):
            if sub.get("action") == "strip" and sub.get("regex"):
                regexes.append(sub["regex"])
    if not regexes:
        regexes = [
            r"(?i)[,\s]+(?:suite|ste\.?|apt\.?|apartment|unit|rm\.?|room|fl\.?|floor|bldg\.?|building)\s*#?\s*(?:\d+[a-z0-9-]*|[a-z](?:\d+|(?=\s*,|\s*$)))",
            r"(?i)[,\s]+#\s*\d+[a-z0-9-]*",
            r"(?i)[,\s]+\d{1,4}(?=,\s*[A-Za-z])",
        ]
    return [re.compile(rx) for rx in regexes]


_CO_PREFIX = re.compile(r"^(?:c/?o,?)\s*[^,\d]*,\s*", re.I)
_CO_DIGIT = re.compile(r"^(?:c/?o,?)\s*.*?(?=\d)", re.I)
_SUITE_REGEXES = _load_strip_regexes()


def _strip_co(address: str) -> str:
    if not address or not re.match(r"(?i)^c/?o", address):
        return address
    if _CO_PREFIX.search(address):
        return _CO_PREFIX.sub("", address, count=1).strip()
    if _CO_DIGIT.search(address):
        return _CO_DIGIT.sub("", address, count=1).strip()
    return address


def _strip_suite(address: str) -> str:
    if not address:
        return address
    result = address
    changed = True
    while changed:
        changed = False
        for rx in _SUITE_REGEXES:
            new = rx.sub("", result).strip()
            new = re.sub(r"\s{2,}", " ", new)
            new = re.sub(r",\s*,", ", ", new)
            if new != result:
                result = new
                changed = True
    return result


def _strip_for_census_strip(address: str) -> str:
    return _strip_suite(_strip_co(address))


def _strip_changes(addr: str) -> bool:
    return _strip_for_census_strip(addr or "") != (addr or "")


def count_candidates(
    con: duckdb.DuckDBPyConnection,
    *,
    nppes_only: bool,
) -> tuple[int, int]:
    source_clause = ""
    if nppes_only:
        source_clause = """
          AND EXISTS (
            SELECT 1 FROM Addresses a
            WHERE a.geocoding_id = g.geocoding_id
              AND a.address_type IN ('nppes_practice', 'nppes_mailing')
          )
        """
    rows = con.execute(
        f"""
        SELECT g.geocoding_id, g.canonical_address
        FROM Geocoding g
        WHERE g.geocoding_status = ?
          AND g.canonical_address IS NOT NULL
          AND TRIM(g.canonical_address) != ''
        {source_clause}
        """,
        [GEOCODING_STATUS_PENDING_API],
    ).fetchall()
    matched = sum(1 for _gid, addr in rows if _strip_changes(addr))
    return len(rows), matched


def reset_candidates(
    con: duckdb.DuckDBPyConnection,
    *,
    nppes_only: bool,
    dry_run: bool,
) -> int:
    source_clause = ""
    if nppes_only:
        source_clause = """
          AND EXISTS (
            SELECT 1 FROM Addresses a
            WHERE a.geocoding_id = g.geocoding_id
              AND a.address_type IN ('nppes_practice', 'nppes_mailing')
          )
        """
    rows = con.execute(
        f"""
        SELECT g.geocoding_id, g.canonical_address
        FROM Geocoding g
        WHERE g.geocoding_status = ?
          AND g.canonical_address IS NOT NULL
          AND TRIM(g.canonical_address) != ''
        {source_clause}
        """,
        [GEOCODING_STATUS_PENDING_API],
    ).fetchall()

    ids = [gid for gid, addr in rows if _strip_changes(addr)]
    if not ids:
        print("No suite-strip candidates found.", flush=True)
        return 0

    print(f"Candidates to reset: {len(ids):,}", flush=True)
    if dry_run:
        return len(ids)

    con.execute("CREATE TEMP TABLE _reset_ids (geocoding_id UUID)")
    con.executemany("INSERT INTO _reset_ids VALUES (?)", [(gid,) for gid in ids])
    con.execute(
        """
        UPDATE Geocoding
        SET
            geocoding_status = 'pending',
            latitude = NULL,
            longitude = NULL,
            colocator = NULL,
            matched_address = NULL,
            geocoding_stage = 'tier1',
            last_attempt = NULL,
            attempt_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE geocoding_id IN (SELECT geocoding_id FROM _reset_ids)
        """
    )
    con.execute("DROP TABLE _reset_ids")
    con.execute("CHECKPOINT")
    return len(ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.path.join(DEFAULT_FINAL_DIR, "irs990.duckdb"))
    parser.add_argument(
        "--nppes-only",
        action="store_true",
        help="Only reset NPPES practice/mailing linked rows",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count only; do not update")
    args = parser.parse_args()

    con = duckdb.connect(args.db)
    try:
        total, matched = count_candidates(con, nppes_only=args.nppes_only)
        scope = "nppes" if args.nppes_only else "all pending_api"
        print(
            f"Scanned {total:,} {scope} rows; "
            f"{matched:,} change under census_strip suite removal",
            flush=True,
        )
        n = reset_candidates(con, nppes_only=args.nppes_only, dry_run=args.dry_run)
        if args.dry_run:
            print(f"Dry run — would reset {n:,} rows to pending", flush=True)
        else:
            pending = con.execute(
                "SELECT COUNT(*) FROM Geocoding WHERE geocoding_status = 'pending'"
            ).fetchone()[0]
            print(f"Reset {n:,} rows → pending. Total pending now: {pending:,}", flush=True)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())