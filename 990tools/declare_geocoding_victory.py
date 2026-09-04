#!/usr/bin/env python3
"""
declare_geocoding_victory.py — Stop bulk Grok/API spend; tier the long tail.

After the overnight preprocess+Grok run, most value is in rules. This script:
  1. Backfills Geocoding.address_count from Addresses
  2. Moves low-weight pending_api rows → geocode_tail (no further API/Grok)
  3. Exports top grok:UNKN rows by address_count for one-shot pattern review
  4. Marks geolocate_grok_overnight_state.json victory_declared=true

High-value work remains: pending_api with address_count >= threshold (default 10),
plus untouched grok_pending. Run geolocate_grok manually on that head only.

Usage:
  python3 declare_geocoding_victory.py --dry-run
  python3 declare_geocoding_victory.py
  python3 declare_geocoding_victory.py --undo   # move geocode_tail back to pending_api
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import duckdb

from constants import (
    GEOCODING_GROK_MIN_ADDRESS_COUNT,
    GEOCODING_STATUS_PENDING_API,
    GEOCODING_STATUS_TAIL,
    GEOCODING_VICTORY_UNKN_EXPORT_FILE,
    GEOCODING_VICTORY_UNKN_EXPORT_ROWS,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb"
DEFAULT_FINAL_DIR = "/Volumes/Data/final"
OVERNIGHT_STATE = ROOT / "geolocate_grok_overnight_state.json"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[victory {ts}] {msg}", flush=True)


def backfill_address_counts(con: duckdb.DuckDBPyConnection, *, dry_run: bool) -> int:
    stale = con.execute(
        "SELECT COUNT(*) FROM Geocoding WHERE address_count IS NULL OR address_count = 0"
    ).fetchone()[0]
    if not stale:
        log("address_count already populated")
        return 0
    log(f"Backfilling address_count for {stale:,} rows")
    if dry_run:
        return stale
    con.execute("""
        UPDATE Geocoding
        SET address_count = (
            SELECT COUNT(*) FROM Addresses
            WHERE Addresses.geocoding_id = Geocoding.geocoding_id
        )
        WHERE address_count IS NULL OR address_count = 0
    """)
    return stale


def tier_pending_api(
    con: duckdb.DuckDBPyConnection,
    *,
    min_count: int,
    dry_run: bool,
) -> Tuple[int, int]:
    """Move pending_api rows below threshold to geocode_tail."""
    row = con.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE COALESCE(address_count, 0) < ?),
            COALESCE(SUM(address_count) FILTER (WHERE COALESCE(address_count, 0) < ?), 0),
            COUNT(*) FILTER (WHERE COALESCE(address_count, 0) >= ?),
            COALESCE(SUM(address_count) FILTER (WHERE COALESCE(address_count, 0) >= ?), 0)
        FROM Geocoding
        WHERE geocoding_status = ?
        """,
        [min_count, min_count, min_count, min_count, GEOCODING_STATUS_PENDING_API],
    ).fetchone()
    tail_rows, tail_refs, head_rows, head_refs = [int(x or 0) for x in row]
    log(
        f"Tier threshold>={min_count}: "
        f"tail→{GEOCODING_STATUS_TAIL} rows={tail_rows:,} refs={tail_refs:,} | "
        f"head stays pending_api rows={head_rows:,} refs={head_refs:,}"
    )
    if tail_rows and not dry_run:
        con.execute(
            f"""
            UPDATE Geocoding
            SET geocoding_status = ?
            WHERE geocoding_status = ?
              AND COALESCE(address_count, 0) < ?
            """,
            [GEOCODING_STATUS_TAIL, GEOCODING_STATUS_PENDING_API, min_count],
        )
    return tail_rows, head_rows


def undo_tail(con: duckdb.DuckDBPyConnection, *, dry_run: bool) -> int:
    n = con.execute(
        f"SELECT COUNT(*) FROM Geocoding WHERE geocoding_status = ?",
        [GEOCODING_STATUS_TAIL],
    ).fetchone()[0]
    log(f"Undo: {n:,} {GEOCODING_STATUS_TAIL} → {GEOCODING_STATUS_PENDING_API}")
    if n and not dry_run:
        con.execute(
            f"""
            UPDATE Geocoding
            SET geocoding_status = ?
            WHERE geocoding_status = ?
            """,
            [GEOCODING_STATUS_PENDING_API, GEOCODING_STATUS_TAIL],
        )
    return n


def export_high_value_unkn(
    con: duckdb.DuckDBPyConnection,
    final_dir: str,
    *,
    limit: int,
    dry_run: bool,
) -> int:
    rows = con.execute(
        """
        SELECT
            geocoding_id,
            address_count,
            canonical_address,
            matched_address,
            normalized_address,
            geocoding_status
        FROM Geocoding
        WHERE geocoding_status = 'grok:UNKN'
        ORDER BY address_count DESC NULLS LAST, canonical_address
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    out_path = os.path.join(final_dir, GEOCODING_VICTORY_UNKN_EXPORT_FILE)
    log(f"Export top {len(rows):,} grok:UNKN → {out_path}")
    if dry_run or not rows:
        return len(rows)

    os.makedirs(final_dir, exist_ok=True)
    tmp = out_path + ".tmp"
    try:
        with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow([
                "geocoding_id",
                "address_count",
                "canonical_address",
                "matched_address",
                "normalized_address",
                "geocoding_status",
            ])
            for row in rows:
                w.writerow(row)
        shutil.move(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return len(rows)


def status_snapshot(con: duckdb.DuckDBPyConnection) -> Dict[str, int]:
    rows = con.execute("""
        SELECT geocoding_status, COUNT(*)::BIGINT
        FROM Geocoding
        WHERE geocoding_status IN (
            'pending_api', 'geocode_tail', 'grok_pending',
            'Match:Grok-4', 'Match:PatternOwners', 'Match:Photon',
            'grok:UNKN', 'grok:VAGUE', 'grok:NOTA', 'grok:AMBIG'
        )
        GROUP BY 1
        ORDER BY 1
    """).fetchall()
    return {status: int(count) for status, count in rows}


def photon_intersection_hint(con: duckdb.DuckDBPyConnection) -> Dict[str, int]:
    """Count Photon matches that look like intersections (suspect point addresses)."""
    row = con.execute("""
        SELECT
            COUNT(*) FILTER (
                WHERE regexp_matches(
                    canonical_address,
                    '(?i)\\b(&|and)\\b.*\\b(hwy|highway|route|rd|road|st|street|ave|blvd)\\b'
                )
            ),
            COUNT(*)
        FROM Geocoding
        WHERE geocoding_status = 'Match:Photon'
    """).fetchone()
    return {
        "photon_total": int(row[1] or 0),
        "photon_intersection_like": int(row[0] or 0),
    }


def mark_victory_state(*, dry_run: bool, min_count: int, summary: Dict[str, Any]) -> None:
    state: Dict[str, Any] = {}
    if OVERNIGHT_STATE.exists():
        state = json.loads(OVERNIGHT_STATE.read_text(encoding="utf-8"))
    state["victory_declared"] = True
    state["victory_at"] = datetime.now().isoformat()
    state["victory_min_address_count"] = min_count
    state["victory_summary"] = summary
    log(f"Marking overnight state victory_declared=true ({OVERNIGHT_STATE.name})")
    if not dry_run:
        OVERNIGHT_STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def clear_victory_state(*, dry_run: bool) -> None:
    if not OVERNIGHT_STATE.exists():
        return
    state = json.loads(OVERNIGHT_STATE.read_text(encoding="utf-8"))
    state.pop("victory_declared", None)
    state.pop("victory_at", None)
    state.pop("victory_min_address_count", None)
    state.pop("victory_summary", None)
    log("Clearing victory_declared from overnight state")
    if not dry_run:
        OVERNIGHT_STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def print_summary(
    counts: Dict[str, int],
    photon: Dict[str, int],
    tail_rows: int,
    head_rows: int,
    min_count: int,
    export_n: int,
) -> None:
    lines = [
        "",
        "════ GEOCODING VICTORY ════",
        f"  Tier: address_count < {min_count} → {GEOCODING_STATUS_TAIL} ({tail_rows:,} rows)",
        f"  Head: address_count >= {min_count} stays pending_api ({head_rows:,} rows)",
        f"  grok_pending: untouched ({counts.get('grok_pending', 0):,} rows) — for later",
        f"  Exported: {export_n:,} top grok:UNKN → {GEOCODING_VICTORY_UNKN_EXPORT_FILE}",
        "",
        "  DB snapshot:",
    ]
    for k in sorted(counts):
        lines.append(f"    {k:22} {counts[k]:>12,}")
    if photon.get("photon_total"):
        lines.append(
            f"  Photon intersection-like: {photon['photon_intersection_like']:,} / "
            f"{photon['photon_total']:,} (preprocess PARTIAL rules catch new ones)"
        )
    lines += [
        "",
        "  Next (optional, ~$20 head-only Grok):",
        f"    GEOCODING_GROK_MIN_ADDRESS_COUNT={min_count} python3 -u irs990processor.py \\",
        "      --step geolocate_grok --max-files 500 \\",
        f"      --final-dir {DEFAULT_FINAL_DIR} --db-path {DEFAULT_DB} --db-threads 1 -v",
        "",
        "  Bulk API pass NOT recommended (slow; Photon intersection false positives).",
        "═" * 28,
    ]
    for line in lines:
        log(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Declare geocoding victory and tier the tail")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--final-dir", default=DEFAULT_FINAL_DIR)
    parser.add_argument(
        "--min-address-count",
        type=int,
        default=GEOCODING_GROK_MIN_ADDRESS_COUNT,
        help="Rows below this move to geocode_tail; head stays for optional Grok",
    )
    parser.add_argument("--export-rows", type=int, default=GEOCODING_VICTORY_UNKN_EXPORT_ROWS)
    parser.add_argument("--dry-run", action="store_true", help="Report only, no DB/state writes")
    parser.add_argument("--undo", action="store_true", help="Move geocode_tail back to pending_api")
    args = parser.parse_args()

    if args.dry_run:
        log("DRY RUN — no writes")

    con = duckdb.connect(args.db_path)
    try:
        if args.undo:
            n = undo_tail(con, dry_run=args.dry_run)
            clear_victory_state(dry_run=args.dry_run)
            log(f"Undo complete ({n:,} rows)")
            return 0

        backfill_address_counts(con, dry_run=args.dry_run)
        tail_rows, head_rows = tier_pending_api(
            con, min_count=args.min_address_count, dry_run=args.dry_run,
        )
        export_n = export_high_value_unkn(
            con, args.final_dir, limit=args.export_rows, dry_run=args.dry_run,
        )
        counts = status_snapshot(con)
        photon = photon_intersection_hint(con)

        summary = {
            "tail_rows": tail_rows,
            "head_rows": head_rows,
            "min_address_count": args.min_address_count,
            "export_rows": export_n,
            "counts": counts,
            "photon": photon,
        }
        mark_victory_state(dry_run=args.dry_run, min_count=args.min_address_count, summary=summary)
        print_summary(counts, photon, tail_rows, head_rows, args.min_address_count, export_n)
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())