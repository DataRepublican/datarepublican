#!/usr/bin/env python3
"""
geolocate_archive_processor.py - Export geocode results for the next rebuild.

BACK bookend of the geolocate pipeline:
  geolocate_prev → census → api → grok → geolocate_archive

1. Finalize Geocoding → Addresses → owners + lat/lon + loose_colocator
   (catches anything census/api/grok left only on Geocoding; pairs with always-on apply)
2. Write {final_dir}/geocode_archive_distinct.tsv.gz so the next rebuild can re-apply
   paid/free geocode results without re-hitting APIs.

Archive columns (canonical_address is the join key):
  canonical_address, colocator, geocoding_status

- colocator: LL:lat:lon, PO:box:zip, FA:…, grok:<CODE>, etc. (on Geocoding)
- geocoding_status: Match:Census, Match:Grok-4, grok:UNKN, …

Note: loose_colocator is NOT archived. It lives on Addresses (and owner tables)
and is computed here (back) and in geolocate_prev (front, after archive load).

Merges with any existing archive so prior results are preserved. Old 2-column
archives (canonical_address + colocator only) still load; missing status is
inferred (Match:Archive, or the grok: colocator itself).
"""

from __future__ import annotations

import csv
import gzip
import os
import shutil
from typing import Dict, Tuple

from database_operations import DatabaseOperations
from logging_utils import log_info, log_warning
from config import global_config
from geolocate_prev_processor import GeolocatePrevProcessor

# (colocator, geocoding_status)
ArchiveRow = Tuple[str, str]


class GeolocateArchiveProcessor:
    """Back bookend: finalize colocators, then export archive TSV."""

    SUCCESS_STATUSES = (
        "Match",
        "Non_Exact",
        "Match:Archive",
        "Tie",
        "Exact",  # legacy status strings if present
    )
    SUCCESS_STATUS_PREFIXES = ("Match:",)

    ARCHIVE_FIELDS = (
        "canonical_address",
        "colocator",
        "geocoding_status",
    )

    def __init__(self, db_ops: DatabaseOperations):
        self.db_ops = db_ops

    def run(self, output_file: str = "geocode_archive_distinct.tsv.gz") -> int:
        output_path = os.path.join(global_config.final_dir, output_file)
        log_info(f"=== Starting geolocate_archive → {output_path} ===")

        # Back bookend: Addresses/owners (+ loose) must catch Geocoding before export.
        # grant_match uses Grants/Charities.colocator; DOT slices use Addresses.colocator.
        GeolocatePrevProcessor(self.db_ops).finalize_colocators_from_geocoding(
            log_prefix="geolocate_archive"
        )

        rows = self._fetch_archive_pairs()
        log_info(f"Fetched {len(rows):,} distinct geocode archive rows from DB")

        merged = self._merge_existing_archive(output_path, rows)
        log_info(f"Merged archive: {len(merged):,} distinct keys (existing + new)")

        self._write_archive(output_path, merged)
        log_info(f"=== geolocate_archive complete: {len(merged):,} rows written ===")
        return len(merged)

    def _fetch_archive_pairs(self) -> Dict[str, ArchiveRow]:
        status_list = ", ".join(f"'{s}'" for s in self.SUCCESS_STATUSES)
        prefix_checks = " OR ".join(
            f"g.geocoding_status LIKE '{pfx}%'" for pfx in self.SUCCESS_STATUS_PREFIXES
        )
        # canonical_address is unique on Geocoding; JOIN Addresses only for colocator fallback.
        result = self.db_ops.execute_query(f"""
            SELECT
                g.canonical_address,
                COALESCE(
                    NULLIF(TRIM(g.colocator), ''),
                    ANY_VALUE(NULLIF(TRIM(a.colocator), ''))
                ) AS colocator,
                g.geocoding_status
            FROM Geocoding g
            LEFT JOIN Addresses a ON a.geocoding_id = g.geocoding_id
            WHERE (
                g.geocoding_status IN ({status_list})
                OR {prefix_checks}
                OR g.geocoding_status LIKE 'grok:%'
            )
              AND g.canonical_address IS NOT NULL
              AND TRIM(g.canonical_address) != ''
              AND COALESCE(
                    NULLIF(TRIM(g.colocator), ''),
                    NULLIF(TRIM(a.colocator), '')
                  ) IS NOT NULL
            GROUP BY
                g.canonical_address,
                g.geocoding_status,
                g.colocator
        """).fetchall()

        out: Dict[str, ArchiveRow] = {}
        for canon, coloc, status in result:
            if not canon or not coloc:
                continue
            coloc_s = str(coloc).strip()
            status_s = str(status).strip() if status else ""
            out[str(canon)] = (coloc_s, status_s)
        return out

    def _merge_existing_archive(
        self, output_path: str, new_rows: Dict[str, ArchiveRow]
    ) -> Dict[str, ArchiveRow]:
        """DB rows win on key collision; keep archive-only keys for continuity."""
        merged: Dict[str, ArchiveRow] = dict(new_rows)
        if not os.path.exists(output_path):
            return merged

        kept_from_file = 0
        try:
            with gzip.open(output_path, "rt", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    canon = (row.get("canonical_address") or "").strip()
                    coloc = (row.get("colocator") or "").strip()
                    if not canon or not coloc:
                        continue
                    if canon in merged:
                        continue
                    status = (row.get("geocoding_status") or "").strip()
                    if not status and coloc.startswith("grok:"):
                        status = coloc
                    merged[canon] = (coloc, status)
                    kept_from_file += 1
            log_info(f"Kept {kept_from_file:,} archive-only keys from existing file")
        except Exception as e:
            log_warning(f"Could not read existing archive for merge: {e}")
        return merged

    def _write_archive(self, output_path: str, rows: Dict[str, ArchiveRow]) -> None:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        tmp_path = output_path + ".tmp"
        try:
            with gzip.open(tmp_path, "wt", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t", lineterminator="\n")
                writer.writerow(list(self.ARCHIVE_FIELDS))
                for canon in sorted(rows.keys()):
                    coloc, status = rows[canon]
                    writer.writerow([canon, coloc, status])
            shutil.move(tmp_path, output_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
