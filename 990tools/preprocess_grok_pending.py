#!/usr/bin/env python3
"""
preprocess_grok_pending.py — One-shot preprocess pass over geocode residual statuses.

Re-applies structured short-circuits + geocoding_patterns.json without API/Grok spend.

Default intake is grok_pending (pre-Grok queue). Use --statuses to re-process
classified Grok failures (e.g. grok:UNKN) after pattern pack updates.

Matched → Match:PatternOwners; unmatched keep their prior status.

Usage:
  python3 preprocess_grok_pending.py --dry-run
  python3 preprocess_grok_pending.py
  python3 preprocess_grok_pending.py --statuses grok:UNKN,grok:VAGUE,grok:NOTA,grok:AMBIG,grok:REDACT
  python3 preprocess_grok_pending.py --max-rows 10000
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from config import global_config
from constants import GEOCODING_PREPROCESS_BATCH_SIZE
from database_operations import DatabaseOperations
from geocoding_api_processor import GeocodingAPIProcessor, GeocodingWorkUnit

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb"
DEFAULT_FINAL_DIR = "/Volumes/Data/final"
DEFAULT_STATUSES = ("grok_pending",)
GROK_FAILURE_STATUSES = (
    "grok:UNKN",
    "grok:VAGUE",
    "grok:NOTA",
    "grok:AMBIG",
    "grok:REDACT",
)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[grok-prep {ts}] {msg}", flush=True)


def _json_safe(val: Any) -> Any:
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if hasattr(val, "hex"):
        return str(val)
    return str(val)


def _status_sql(statuses: Sequence[str]) -> Tuple[str, Tuple[str, ...]]:
    placeholders = ", ".join("?" for _ in statuses)
    return f"geocoding_status IN ({placeholders})", tuple(statuses)


def fetch_batch(
    db_ops: DatabaseOperations,
    statuses: Sequence[str],
    limit: int,
    after_id: Optional[str] = None,
) -> List[tuple]:
    status_sql, status_params = _status_sql(statuses)
    if after_id:
        return db_ops.execute_query(
            f"""
            SELECT geocoding_id, normalized_address, attempt_count, canonical_address,
                   address_count, geocoding_status
            FROM Geocoding
            WHERE {status_sql} AND geocoding_id > ?
            ORDER BY geocoding_id
            LIMIT ?
            """,
            (*status_params, after_id, limit),
        ).fetchall()
    return db_ops.execute_query(
        f"""
        SELECT geocoding_id, normalized_address, attempt_count, canonical_address,
               address_count, geocoding_status
        FROM Geocoding
        WHERE {status_sql}
        ORDER BY geocoding_id
        LIMIT ?
        """,
        (*status_params, limit),
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
            "geocoding_status": row[5] if len(row) > 5 else DEFAULT_STATUSES[0],
        }
        units.append(GeocodingWorkUnit.work_item("grok_pending_preprocess", data))
    return units


def count_statuses(db_ops: DatabaseOperations, statuses: Sequence[str]) -> int:
    status_sql, status_params = _status_sql(statuses)
    row = db_ops.execute_query(
        f"SELECT COUNT(*) FROM Geocoding WHERE {status_sql}",
        status_params,
    ).fetchone()
    return int(row[0]) if row else 0


def count_status(db_ops: DatabaseOperations, status: str) -> int:
    return count_statuses(db_ops, (status,))


def parse_statuses(raw: Optional[str], grok_failures: bool) -> Tuple[str, ...]:
    if grok_failures:
        return GROK_FAILURE_STATUSES
    if not raw:
        return DEFAULT_STATUSES
    parts = tuple(s.strip() for s in raw.split(",") if s.strip())
    if not parts:
        return DEFAULT_STATUSES
    return parts


def main() -> int:
    parser = argparse.ArgumentParser(description="Preprocess grok residual with pattern rules")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--final-dir", default=DEFAULT_FINAL_DIR)
    parser.add_argument("--batch-size", type=int, default=GEOCODING_PREPROCESS_BATCH_SIZE)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--statuses",
        default=None,
        help="Comma-separated geocoding_status values (default: grok_pending)",
    )
    parser.add_argument(
        "--grok-failures",
        action="store_true",
        help="Shorthand for all grok:UNKN/VAGUE/NOTA/AMBIG/REDACT statuses",
    )
    args = parser.parse_args()
    statuses = parse_statuses(args.statuses, args.grok_failures)

    # Public Photon only — avoid hanging probe on offline self-host
    os.environ.pop("PHOTON_DOMAIN", None)
    os.environ.pop("PHOTON_SCHEME", None)

    global_config.final_dir = args.final_dir
    global_config.db_path = args.db_path

    if args.dry_run:
        import duckdb

        con = duckdb.connect(args.db_path, read_only=True)
        status_sql, status_params = _status_sql(statuses)
        pending = con.execute(
            f"SELECT COUNT(*) FROM Geocoding WHERE {status_sql}",
            list(status_params),
        ).fetchone()[0]
        by = con.execute(
            f"""
            SELECT geocoding_status, COUNT(*)::BIGINT
            FROM Geocoding WHERE {status_sql}
            GROUP BY 1 ORDER BY 2 DESC
            """,
            list(status_params),
        ).fetchall()
        con.close()
        log(f"DRY RUN — {pending:,} rows in statuses={list(statuses)}")
        for st, n in by:
            log(f"  {st}={n:,}")
        return 0

    DatabaseOperations.closePool()
    DatabaseOperations.bootstrap(args.db_path, dbUI=False)
    db_ops = DatabaseOperations(args.db_path, threads=1, init_schema=False)
    proc = GeocodingAPIProcessor(db_ops)
    proc.pipeline_step = "grok_pending_preprocess"

    total_pending = count_statuses(db_ops, statuses)
    log(
        f"Starting preprocess: {total_pending:,} rows "
        f"statuses={list(statuses)} batch={args.batch_size:,}"
    )

    scanned = 0
    matched = 0
    batches = 0
    budget = args.max_rows
    after_id: Optional[str] = None

    while True:
        if budget is not None and scanned >= budget:
            break
        limit = args.batch_size
        if budget is not None:
            limit = min(limit, budget - scanned)
            if limit <= 0:
                break

        rows = fetch_batch(db_ops, statuses, limit, after_id=after_id)
        if not rows:
            break

        after_id = str(rows[-1][0])
        units = rows_to_units(rows)
        _, batch_matched = proc.apply_preprocess_batch(units)
        scanned += len(rows)
        matched += batch_matched
        batches += 1
        remaining = count_statuses(db_ops, statuses)
        log(
            f"batch {batches}: scanned={len(rows):,} matched={batch_matched:,} "
            f"cumulative={matched:,}/{scanned:,} intake_left={remaining:,}"
        )
        if len(rows) < limit:
            break

    owners = count_status(db_ops, "Match:PatternOwners")
    remaining = count_statuses(db_ops, statuses)
    log("")
    log("════ GROK RESIDUAL PREPROCESS DONE ════")
    log(f"  statuses:      {list(statuses)}")
    log(f"  scanned:       {scanned:,}")
    log(f"  matched:       {matched:,} → Match:PatternOwners")
    log(f"  intake_left:   {remaining:,}")
    log(f"  PatternOwners: {owners:,}")
    log("═" * 36)
    db_ops.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
