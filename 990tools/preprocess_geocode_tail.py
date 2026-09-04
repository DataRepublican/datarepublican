#!/usr/bin/env python3
"""
preprocess_geocode_tail.py — One-shot preprocess pass over geocode_tail rows.

Applies geocoding_patterns.json (including victory-era rules) without API/Grok spend.
Matched rows become Match:PatternOwners; unmatched stay geocode_tail.

Usage:
  python3 preprocess_geocode_tail.py --dry-run
  python3 preprocess_geocode_tail.py
  python3 preprocess_geocode_tail.py --max-rows 50000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from config import global_config
from constants import GEOCODING_PREPROCESS_BATCH_SIZE, GEOCODING_STATUS_TAIL
from database_operations import DatabaseOperations
from geocoding_api_processor import GeocodingAPIProcessor, GeocodingWorkUnit

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb"
DEFAULT_FINAL_DIR = "/Volumes/Data/final"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[tail-preprocess {ts}] {msg}", flush=True)


def _json_safe(val: Any) -> Any:
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if hasattr(val, "hex"):
        return str(val)
    return str(val)


def fetch_tail_batch(
    db_ops: DatabaseOperations,
    limit: int,
    after_id: str | None = None,
) -> List[tuple]:
    if after_id:
        return db_ops.execute_query(
            """
            SELECT geocoding_id, normalized_address, attempt_count, canonical_address, address_count
            FROM Geocoding
            WHERE geocoding_status = ? AND geocoding_id > ?
            ORDER BY geocoding_id
            LIMIT ?
            """,
            (GEOCODING_STATUS_TAIL, after_id, limit),
        ).fetchall()
    return db_ops.execute_query(
        """
        SELECT geocoding_id, normalized_address, attempt_count, canonical_address, address_count
        FROM Geocoding
        WHERE geocoding_status = ?
        ORDER BY geocoding_id
        LIMIT ?
        """,
        (GEOCODING_STATUS_TAIL, limit),
    ).fetchall()


def rows_to_units(rows: List[tuple]) -> List[GeocodingWorkUnit]:
    units = []
    for row in rows:
        norm = row[1]
        if isinstance(norm, str):
            try:
                norm = json.loads(norm)
            except json.JSONDecodeError:
                norm = {}
        data = {
            "geocoding_id": _json_safe(row[0]),
            "normalized_address": norm,
            "attempt_count": row[2] or 0,
            "canonical_address": row[3],
            "address_count": row[4] or 0,
            "geocoding_status": GEOCODING_STATUS_TAIL,
        }
        units.append(GeocodingWorkUnit.work_item("tail_preprocess", data))
    return units


def count_tail(db_ops: DatabaseOperations) -> int:
    row = db_ops.execute_query(
        "SELECT COUNT(*) FROM Geocoding WHERE geocoding_status = ?",
        (GEOCODING_STATUS_TAIL,),
    ).fetchone()
    return int(row[0]) if row else 0


def snapshot(db_ops: DatabaseOperations) -> Dict[str, int]:
    rows = db_ops.execute_query(
        """
        SELECT geocoding_status, COUNT(*)::BIGINT, COALESCE(SUM(address_count), 0)::BIGINT
        FROM Geocoding
        WHERE geocoding_status IN (?, 'Match:PatternOwners')
        GROUP BY 1
        """,
        (GEOCODING_STATUS_TAIL,),
    ).fetchall()
    return {status: int(count) for status, count, _ in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Preprocess geocode_tail with pattern rules")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--final-dir", default=DEFAULT_FINAL_DIR)
    parser.add_argument("--batch-size", type=int, default=GEOCODING_PREPROCESS_BATCH_SIZE)
    parser.add_argument("--max-rows", type=int, default=None, help="Stop after N tail rows scanned")
    parser.add_argument("--dry-run", action="store_true", help="Count only; no DB writes")
    args = parser.parse_args()

    global_config.final_dir = args.final_dir
    global_config.db_path = args.db_path

    pending = 0
    if args.dry_run:
        import duckdb
        con = duckdb.connect(args.db_path, read_only=True)
        pending = con.execute(
            "SELECT COUNT(*) FROM Geocoding WHERE geocoding_status = ?",
            [GEOCODING_STATUS_TAIL],
        ).fetchone()[0]
        con.close()
        log(f"DRY RUN — {pending:,} {GEOCODING_STATUS_TAIL} rows would be scanned")
        return 0

    DatabaseOperations.bootstrap(args.db_path, dbUI=False)
    db_ops = DatabaseOperations(args.db_path, threads=1, init_schema=False)
    proc = GeocodingAPIProcessor(db_ops)
    proc.pipeline_step = "geocode_tail"

    total_pending = count_tail(db_ops)
    log(f"Starting tail preprocess: {total_pending:,} rows (batch={args.batch_size:,})")

    scanned = 0
    matched = 0
    batches = 0
    budget = args.max_rows
    after_id: str | None = None

    while True:
        if budget is not None and scanned >= budget:
            break
        limit = args.batch_size
        if budget is not None:
            limit = min(limit, budget - scanned)
            if limit <= 0:
                break

        rows = fetch_tail_batch(db_ops, limit, after_id=after_id)
        if not rows:
            break

        after_id = str(rows[-1][0])
        units = rows_to_units(rows)
        _, batch_matched = proc.apply_preprocess_batch(units)
        scanned += len(rows)
        matched += batch_matched
        batches += 1
        remaining = count_tail(db_ops)
        log(
            f"batch {batches}: scanned={len(rows):,} matched={batch_matched:,} "
            f"cumulative={matched:,}/{scanned:,} tail_remaining={remaining:,}"
        )
        if len(rows) < limit:
            break

    owners_before = db_ops.execute_query(
        "SELECT COUNT(*) FROM Geocoding WHERE geocoding_status = 'Match:PatternOwners'"
    ).fetchone()[0]
    tail_remaining = count_tail(db_ops)
    log("")
    log("════ TAIL PREPROCESS DONE ════")
    log(f"  scanned:  {scanned:,}")
    log(f"  matched:  {matched:,} → Match:PatternOwners")
    log(f"  tail left: {tail_remaining:,}")
    log(f"  PatternOwners total: {owners_before:,}")
    log("═" * 28)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())