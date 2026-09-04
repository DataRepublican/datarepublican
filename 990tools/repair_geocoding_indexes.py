#!/usr/bin/env python3
"""Recover from DuckDB ART SIGSEGV on Geocoding scans after unclean shutdown.

Typical crash:
  duckdb::ART::InsertKeys → ApplyBufferedReplays → TableIndexList::Bind

Fix order (DB must not be open):
  1. Move irs990.duckdb.wal aside — do NOT try CHECKPOINT on a bad WAL
  2. Open DB, drop Geocoding ART indexes, close
  3. Move WAL back to irs990.duckdb.wal
  4. Open DB again — DuckDB replays the WAL (indexes gone, no ART SIGSEGV)
  5. CHECKPOINT to merge replayed writes into the main DB file

Census pagination uses geocoding_id; indexes are not needed during the run.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb


def _wal_path(db_path: str) -> Path:
    return Path(f"{db_path}.wal")


def move_wal_aside(db_path: str, *, dest: str | None = None) -> Path | None:
    wal = _wal_path(db_path)
    if not wal.exists():
        print(f"No WAL at {wal} — nothing to move", flush=True)
        return None
    if dest:
        target = Path(dest)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = wal.with_name(f"{wal.name}.corrupt_{stamp}")
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing {target}")
    size_mb = wal.stat().st_size / (1024 * 1024)
    print(f"Moving {wal} ({size_mb:.0f} MB) → {target}", flush=True)
    shutil.move(str(wal), str(target))
    print(f"WAL moved aside: {target}", flush=True)
    return target


def repair(db_path: str, *, recreate: bool = False, skip_move_wal: bool = False) -> None:
    if not skip_move_wal:
        move_wal_aside(db_path)

    print(f"Opening {db_path}...", flush=True)
    t0 = time.time()
    con = duckdb.connect(db_path)
    print(f"Connected in {time.time() - t0:.1f}s", flush=True)

    for idx in ("idx_geocoding_status", "idx_geocoding_canonical"):
        print(f"Dropping {idx}...", flush=True)
        con.execute(f"DROP INDEX IF EXISTS {idx}")
        print(f"  dropped {idx}", flush=True)

    print("CHECKPOINT...", flush=True)
    con.execute("CHECKPOINT")
    print(f"CHECKPOINT done ({time.time() - t0:.1f}s total)", flush=True)

    print("Testing Geocoding pending count...", flush=True)
    pending = con.execute(
        "SELECT COUNT(*) FROM Geocoding "
        "WHERE geocoding_status IS NULL OR geocoding_status IN ('pending', 'owners')"
    ).fetchone()[0]
    print(f"pending={pending:,}", flush=True)

    if recreate:
        print("Recreating idx_geocoding_status (may take a long time)...", flush=True)
        con.execute("CREATE INDEX idx_geocoding_status ON Geocoding(geocoding_status)")
        print("Recreating idx_geocoding_canonical...", flush=True)
        con.execute("CREATE INDEX idx_geocoding_canonical ON Geocoding(canonical_address)")
        con.execute("CHECKPOINT")
        print("Indexes recreated.", flush=True)

    con.close()
    print("Repair complete.", flush=True)


def restore_wal(db_path: str, wal_src: str) -> Path:
    """Move a saved WAL back beside the DB so DuckDB can replay it on next open."""
    target = _wal_path(db_path)
    source = Path(wal_src)
    if not source.exists():
        raise FileNotFoundError(f"WAL source not found: {source}")
    if target.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing WAL at {target} — move it aside first"
        )
    size_mb = source.stat().st_size / (1024 * 1024)
    print(f"Restoring {source} ({size_mb:.0f} MB) → {target}", flush=True)
    shutil.move(str(source), str(target))
    print(f"WAL restored: {target}", flush=True)
    return target


def replay_wal(db_path: str, *, checkpoint: bool = True) -> None:
    """Open DB with WAL present (indexes must already be dropped) and replay + checkpoint."""
    wal = _wal_path(db_path)
    if not wal.exists():
        raise FileNotFoundError(f"No WAL at {wal} — nothing to replay")

    print(f"Opening {db_path} to replay WAL ({wal.stat().st_size / (1024**3):.1f} GB)...", flush=True)
    t0 = time.time()
    con = duckdb.connect(db_path)
    print(f"Connected + WAL replayed in {time.time() - t0:.1f}s", flush=True)

    print("Verifying Geocoding status counts...", flush=True)
    rows = con.execute(
        "SELECT geocoding_status, COUNT(*) c FROM Geocoding "
        "GROUP BY 1 ORDER BY c DESC LIMIT 12"
    ).fetchall()
    for status, count in rows:
        print(f"  {status!r:22} {count:>12,}", flush=True)

    pending = con.execute(
        "SELECT COUNT(*) FROM Geocoding "
        "WHERE geocoding_status IS NULL OR geocoding_status IN ('pending', 'owners')"
    ).fetchone()[0]
    print(f"pending={pending:,}", flush=True)

    if checkpoint:
        print("CHECKPOINT...", flush=True)
        con.execute("CHECKPOINT")
        print(f"CHECKPOINT done ({time.time() - t0:.1f}s total)", flush=True)
        if wal.exists():
            print(f"WAL still present after CHECKPOINT: {wal.stat().st_size / (1024**2):.0f} MB", flush=True)
        else:
            print("WAL fully merged (no .wal file remaining)", flush=True)

    con.close()
    print("Replay complete.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="/Volumes/Data/final/irs990.duckdb")
    parser.add_argument(
        "--wal-dest",
        help="Explicit path to move WAL to (default: <db>.wal.corrupt_YYYYMMDD_HHMMSS)",
    )
    parser.add_argument(
        "--skip-move-wal",
        action="store_true",
        help="Skip moving WAL (only if already moved or absent)",
    )
    parser.add_argument(
        "--move-wal-only",
        action="store_true",
        help="Only move WAL aside and exit (stop pipeline first)",
    )
    parser.add_argument(
        "--restore-wal",
        metavar="PATH",
        help="Move saved WAL back to <db>.wal (phase 2 — indexes must already be dropped)",
    )
    parser.add_argument(
        "--replay-wal-only",
        action="store_true",
        help="Open DB to replay existing .wal and CHECKPOINT (skip move/drop phases)",
    )
    parser.add_argument(
        "--recreate", action="store_true",
        help="Rebuild indexes after drop (slow; not needed for census geocoding_id pagination)",
    )
    args = parser.parse_args()

    if args.replay_wal_only:
        try:
            replay_wal(args.db)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0

    if args.restore_wal:
        try:
            restore_wal(args.db, args.restore_wal)
            replay_wal(args.db)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0

    if args.move_wal_only:
        try:
            move_wal_aside(args.db, dest=args.wal_dest)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0

    try:
        if not args.skip_move_wal:
            move_wal_aside(args.db, dest=args.wal_dest)
        repair(args.db, recreate=args.recreate, skip_move_wal=True)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())