#!/usr/bin/env python3
"""
stats_command.py - Command-line tool to generate database statistics reports

Usage:
  python stats_command.py <step_name> [notes]
  python stats_command.py after_address --db-path /Volumes/Data/final/irs990.duckdb
"""

import argparse
import os
import sys

from database_operations import DatabaseOperations

DEFAULT_FINAL_DIR = "/Volumes/Data/final"


def resolve_db_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_path = os.environ.get("IRS990_DB_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    candidates = [
        os.path.join(DEFAULT_FINAL_DIR, "irs990.duckdb"),
        "irs990.duckdb",
        "final/irs990.duckdb",
        "../final/irs990.duckdb",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return os.path.join(DEFAULT_FINAL_DIR, "irs990.duckdb")


def main():
    parser = argparse.ArgumentParser(description="Generate IRS 990 database statistics report")
    parser.add_argument("step_name", help="Report suffix, e.g. after_address")
    parser.add_argument("notes", nargs="?", default="", help="Optional notes for the report")
    parser.add_argument("--db-path", help="Path to irs990.duckdb (default: production final dir)")
    args = parser.parse_args()

    db_path = resolve_db_path(args.db_path)
    if not os.path.exists(db_path):
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    try:
        DatabaseOperations.bootstrap(db_path)
        db_ops = DatabaseOperations(db_path)
        stats_processor = db_ops.get_stats_processor()
        report_file = stats_processor.generate_stats_report(args.step_name, args.notes)
        print(f"Statistics report generated: {report_file}")

        counts = stats_processor.get_table_counts()
        total = sum(counts.values())
        print(f"\nDatabase: {db_path}")
        print(f"Total records (known tables): {total:,}")

        ext = stats_processor.get_external_reference_analysis()
        for group, ingested in ext.get("ingested", {}).items():
            print(f"  {group}: {'ingested' if ingested else 'not present'}")

        shared = stats_processor.get_shared_canonical_analysis()
        print(f"Multi-type canonical addresses: {shared.get('multi_type_canonicals', 0):,}")

        for table, count in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            if count > 0:
                print(f"  {table}: {count:,}")

        db_ops.close()
        DatabaseOperations.closePool()

    except Exception as e:
        print(f"Error generating stats report: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()