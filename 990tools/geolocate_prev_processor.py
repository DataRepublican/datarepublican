#!/usr/bin/env python3
"""
geolocate_prev_processor.py - Fast geolocation from prior-run archive cache.

FRONT bookend of the geolocate pipeline:
  geolocate_prev → census → api → grok → geolocate_archive (BACK bookend)

0. Delete empty address shells (no street/city/zip, no geocoding_id, no colocator).
   XML often emits officer/contractor Address rows with no USAddress content;
   address-dedup never creates a Geocoding row for blank canonical_address, so
   they never collapse to one master geocode and only waste space / pollute stats.
1. Load geocode_archive_distinct.tsv.gz → Geocoding (colocator + geocoding_status)
   Columns: canonical_address, colocator, [geocoding_status]
   Older 2-column archives (canonical + colocator only) still work.
2. Propagate Geocoding → Addresses → owners (so archive hits are live before census)
3. Backfill lat/lon from colocator (PO: / LL:)
4. Compute loose_colocator (0.5° grid) on Addresses + owners —
   loose_colocator is NOT stored on Geocoding and is not part of the archive.

New LL: from census/api/grok are applied live (Addresses+owners on each match)
and finalized again at geolocate_archive (same finalize_colocators_from_geocoding).
"""

from __future__ import annotations

import csv
import gzip
import os
from typing import List, Optional, Tuple

from database_operations import DatabaseOperations
from logging_utils import log_info, log_error, log_warning
from config import global_config

# (canonical_address, colocator, geocoding_status)
ArchiveChunkRow = Tuple[str, str, str]

# Address rows that carry no location signal and never entered Geocoding.
# Keep FA:/PO:/LL: colocators even if street fields are blank (foreign / PO).
EMPTY_ADDRESS_WHERE = """
    geocoding_id IS NULL
    AND COALESCE(TRIM(address_line1), '') = ''
    AND COALESCE(TRIM(address_line2), '') = ''
    AND COALESCE(TRIM(city), '') = ''
    AND COALESCE(TRIM(zip_code), '') = ''
    AND COALESCE(TRIM(po_box), '') = ''
    AND (colocator IS NULL OR TRIM(colocator) = '')
"""


class GeolocatePrevProcessor:
    """Archive-cache geolocation + later loose_colocator population on Addresses/owners."""

    def __init__(self, db_ops: DatabaseOperations):
        self.db_ops = db_ops

    def run(self, max_files: int | None = None) -> int:
        log_info("=== Starting geolocate_prev (archive cache + loose colocator) ===")

        deleted = self.delete_empty_address_shells()
        log_info(f"Empty address shells removed: {deleted:,}")

        self._ensure_zips_table()
        self.db_ops.execute_query("ALTER TABLE Geocoding ADD COLUMN IF NOT EXISTS colocator VARCHAR;")

        updated = self.apply_geocode_archive_cache()
        log_info(f"Archive cache applied: {updated:,} Geocoding records touched")

        # DEFER Geocoding→Addresses→owners colocator/lat-lon finalize.
        # On 16GB hosts with ~94M Addresses, those UPDATEs OOM and poison the
        # singleton DuckDB write connection so geolocate_census never starts.
        # Re-run finalize at geolocate_archive (or a dedicated low-memory pass)
        # after census has cleared the pending queue.
        import os
        if os.environ.get("GEOLOCATE_PREV_FINALIZE", "").strip() in ("1", "true", "yes"):
            try:
                self.finalize_colocators_from_geocoding(log_prefix="geolocate_prev")
            except Exception as e:
                log_warning(
                    f"geolocate_prev finalize colocators failed (non-fatal): {e}"
                )
        else:
            log_info(
                "Skipping colocator finalize in geolocate_prev "
                "(set GEOLOCATE_PREV_FINALIZE=1 to force). "
                "Will run at geolocate_archive bookend."
            )
            print(
                "[geolocate_prev] Skipping colocator finalize → free RAM for census",
                flush=True,
            )

        log_info("=== geolocate_prev complete ===")
        return updated

    def delete_empty_address_shells(self) -> int:
        """
        Remove Addresses with no geocodable content.

        Why they exist: officer/contractor build_address() always creates a row;
        XML often omits USAddress. Address dedup only groups non-empty
        canonical_address, so blanks never share one Geocoding record — each
        stays a self-master orphan with null geocoding_id.

        Safe: requires null geocoding_id and no colocator (preserves FA:/PO: shells).
        """
        log_info("Deleting empty address shells (no fields, no geocoding_id, no colocator)...")
        print("[geolocate_prev] Counting empty address shells...", flush=True)

        with self.db_ops.acquire_write_conn() as conn:
            # Breakdown for the log before delete
            try:
                by_type = conn.execute(f"""
                    SELECT COALESCE(address_type, '(null)'), COUNT(*)::BIGINT
                    FROM Addresses
                    WHERE {EMPTY_ADDRESS_WHERE}
                    GROUP BY 1
                    ORDER BY 2 DESC
                """).fetchall()
                for at, c in by_type:
                    log_info(f"  empty shell {at}: {c:,}")
                    print(f"[geolocate_prev]   empty shell {at}: {c:,}", flush=True)
            except Exception as e:
                log_warning(f"Could not pre-count empty shells by type: {e}")

            before = conn.execute(f"""
                SELECT COUNT(*) FROM Addresses WHERE {EMPTY_ADDRESS_WHERE}
            """).fetchone()[0]
            if before == 0:
                log_info("No empty address shells to delete")
                print("[geolocate_prev] No empty address shells", flush=True)
                return 0

            print(f"[geolocate_prev] Deleting {before:,} empty address shells...", flush=True)
            conn.execute("BEGIN TRANSACTION")
            try:
                # DuckDB DELETE returns affected row count via fetchone on some versions
                result = conn.execute(f"""
                    DELETE FROM Addresses
                    WHERE {EMPTY_ADDRESS_WHERE}
                """)
                deleted = before
                try:
                    row = result.fetchone() if result is not None else None
                    if row and row[0] is not None:
                        deleted = int(row[0])
                except Exception:
                    pass
                # Verify
                remaining = conn.execute(f"""
                    SELECT COUNT(*) FROM Addresses WHERE {EMPTY_ADDRESS_WHERE}
                """).fetchone()[0]
                if remaining:
                    # If DELETE count unreliable, use before - remaining
                    deleted = before - remaining
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

            log_info(f"Deleted {deleted:,} empty address shells ({remaining:,} remain)")
            print(
                f"[geolocate_prev] Deleted {deleted:,} empty address shells "
                f"({remaining:,} remain)",
                flush=True,
            )
            return int(deleted)

    def _ensure_zips_table(self):
        """Build the Zips lookup table if it doesn't exist (idempotent)."""
        try:
            count = self.db_ops.execute_query("SELECT COUNT(*) FROM Zips").fetchone()[0]
            if count > 0:
                log_info(f"Zips table already has {count:,} rows")
                return
        except Exception:
            pass

        log_info("Building Zips table from US_zips.txt.gz (required for PO: handling)...")
        zip_file_path = os.path.join(os.getcwd(), "US_zips.txt.gz")

        self.db_ops.execute_query("DROP TABLE IF EXISTS Zips;")
        self.db_ops.execute_query("""
        CREATE TABLE Zips (
            country_code   VARCHAR,
            zip            VARCHAR PRIMARY KEY,
            place_name     VARCHAR,
            state_name     VARCHAR,
            state_code     VARCHAR,
            region_name    VARCHAR,
            region_code    VARCHAR,
            extra1         VARCHAR,
            extra2         VARCHAR,
            extra3         VARCHAR,
            lat            DOUBLE,
            lon            DOUBLE,
            accuracy       INTEGER
        );
        """)

        try:
            self.db_ops.execute_query(f"""
            COPY Zips FROM '{zip_file_path}' (
                FORMAT CSV,
                DELIMITER '\t',
                HEADER FALSE,
                COMPRESSION 'gzip'
            );
            """)
            count = self.db_ops.execute_query("SELECT COUNT(*) FROM Zips").fetchone()[0]
            log_info(f"Zips table built with {count:,} rows")
        except Exception as e:
            log_warning(f"Could not load Zips table: {e}. PO: handling may be limited.")
            self.db_ops.execute_query(
                "CREATE TABLE IF NOT EXISTS Zips (zip VARCHAR PRIMARY KEY, lat DOUBLE, lon DOUBLE);"
            )

        self.db_ops.execute_query("CREATE INDEX IF NOT EXISTS idx_zips_zip ON Zips(zip);")

    def _tune_conn(self, conn):
        import os
        mem = os.environ.get("DUCKDB_MEMORY_LIMIT", "8GB")
        conn.execute("SET preserve_insertion_order=false")
        conn.execute("SET threads=1")
        conn.execute(f"SET memory_limit='{mem}'")

    def _safe_commit(self, conn, label: str) -> None:
        try:
            conn.commit()
        except Exception as ex:
            log_warning(f"commit after {label}: {ex}")
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass

    def _archive_already_applied_count(self, conn) -> int:
        """Rows that look like archive/API wins (idempotency skip signal)."""
        return conn.execute("""
            SELECT COUNT(*) FROM Geocoding
            WHERE colocator IS NOT NULL AND TRIM(colocator) != ''
              AND (
                    geocoding_status = 'Match:Archive'
                 OR geocoding_status LIKE 'Match:%'
                 OR geocoding_status LIKE 'grok:%'
              )
        """).fetchone()[0]

    def apply_geocode_archive_cache(self, cache_file: str = "geocode_archive_distinct.tsv.gz") -> int:
        """Load pre-geocoded archive and propagate colocators to owners."""
        actual_cache_file = os.path.join(global_config.final_dir, cache_file)

        if not os.path.exists(actual_cache_file):
            log_warning(f"Geocode archive not found at {actual_cache_file} — skipping cache load")
            return 0

        with self.db_ops.acquire_write_conn() as conn:
            already_done = self._archive_already_applied_count(conn)

        # Production post-geolocate has ~13M+ matched rows; skip re-stream when saturated.
        archive_skip_threshold = 2_400_000
        try:
            if already_done >= archive_skip_threshold:
                log_info(
                    f"Archive cache already applied ({already_done:,} matched/colocated) — skipping TSV stream"
                )
                print(
                    f"[geolocate_prev] Archive already loaded ({already_done:,} rows), skipping stream",
                    flush=True,
                )
                total_geocoding = already_done
            else:
                if already_done > 0:
                    log_info(f"Resuming archive cache ({already_done:,} rows already matched/colocated)")
                log_info(f"Streaming geocode cache from {actual_cache_file}...")
                print(f"[geolocate_prev] Streaming archive from {actual_cache_file}", flush=True)
                chunk_size = 20000
                total_geocoding = 0
                chunk_num = 0

                with gzip.open(actual_cache_file, "rt", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter="\t")
                    chunk: List[ArchiveChunkRow] = []
                    for row in reader:
                        parsed = self._parse_archive_row(row)
                        if not parsed:
                            continue
                        chunk.append(parsed)
                        if len(chunk) >= chunk_size:
                            chunk_num += 1
                            total_geocoding += self._commit_archive_chunk(
                                chunk, chunk_num, total_geocoding
                            )
                            chunk = []
                    if chunk:
                        chunk_num += 1
                        total_geocoding += self._commit_archive_chunk(
                            chunk, chunk_num, total_geocoding
                        )

            # Skip VACUUM ANALYZE here — it pins multi‑GB on 16GB hosts and leaves the
            # write connection near the memory ceiling so finalize OOMs immediately.
            # ANALYZE can run later via optimize_database after census.
            log_info(f"Archive cache load complete: {total_geocoding:,} Geocoding records updated")
            print(f"[geolocate_prev] Archive cache complete: {total_geocoding:,} rows", flush=True)
            return total_geocoding

        except Exception as e:
            log_error(f"Archive cache load failed: {e}", exc_info=True)
            raise

    @staticmethod
    def _parse_archive_row(row: dict) -> Optional[ArchiveChunkRow]:
        """Normalize a TSV dict into (canon, colocator, status)."""
        if not row:
            return None
        canon = (row.get("canonical_address") or "").strip()
        coloc = (row.get("colocator") or "").strip()
        if not canon or not coloc:
            return None
        status = (row.get("geocoding_status") or "").strip()
        if not status:
            # Legacy 2-col archive, or status omitted
            status = coloc if coloc.startswith("grok:") else "Match:Archive"
        return (canon, coloc, status)

    def _commit_archive_chunk(
        self, chunk: List[ArchiveChunkRow], chunk_num: int, total_so_far: int
    ) -> int:
        """Apply one archive chunk on a fresh write connection to avoid memory accumulation."""
        with self.db_ops.acquire_write_conn() as conn:
            self._tune_conn(conn)
            try:
                conn.execute("BEGIN TRANSACTION")
                updated = self._apply_archive_chunk(conn, chunk, chunk_num)
                conn.commit()
                print(
                    f"[geolocate_prev] Committed chunk {chunk_num} "
                    f"(+{updated:,}, {total_so_far + updated:,} geocoding rows total)",
                    flush=True,
                )
                return updated
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

    def _apply_archive_chunk(self, conn, chunk: List[ArchiveChunkRow], chunk_num: int) -> int:
        if not chunk:
            return 0

        log_info(f"[geolocate_prev] Processing archive chunk {chunk_num} ({len(chunk):,} rows)...")
        print(f"[geolocate_prev] Processing archive chunk {chunk_num} ({len(chunk):,} rows)...", flush=True)

        conn.execute("""
            CREATE OR REPLACE TEMP TABLE chunk_cache (
                canonical_address VARCHAR,
                colocator VARCHAR,
                geocoding_status VARCHAR
            )
        """)

        def _esc(s: str) -> str:
            return str(s or "").replace("'", "''")

        safe_chunk = [(_esc(ca), _esc(co), _esc(st)) for ca, co, st in chunk]
        batch_size = 2000
        for i in range(0, len(safe_chunk), batch_size):
            sub = safe_chunk[i : i + batch_size]
            values = ", ".join(f"('{ca}', '{co}', '{st}')" for ca, co, st in sub)
            conn.execute(f"INSERT INTO chunk_cache VALUES {values}")

        conn.execute("""
            CREATE OR REPLACE TEMP TABLE update_map AS
            SELECT
                g.geocoding_id,
                c.colocator,
                CASE
                    WHEN NULLIF(TRIM(c.geocoding_status), '') IS NOT NULL
                        THEN TRIM(c.geocoding_status)
                    WHEN c.colocator LIKE 'grok:%' THEN c.colocator
                    ELSE 'Match:Archive'
                END AS target_status,
                CASE WHEN c.colocator LIKE 'LL:%'
                     THEN TRY_CAST(split_part(c.colocator, ':', 2) AS DOUBLE)
                     ELSE NULL END AS parsed_lat,
                CASE WHEN c.colocator LIKE 'LL:%'
                     THEN TRY_CAST(split_part(c.colocator, ':', 3) AS DOUBLE)
                     ELSE NULL END AS parsed_lon
            FROM Geocoding g
            INNER JOIN chunk_cache c ON g.canonical_address = c.canonical_address
            WHERE g.geocoding_status IS NULL
               OR g.geocoding_status IN (
                    'pending', 'owners', 'No_Match',
                    'pending_api', 'geocode_tail', 'grok_pending'
               )
        """)

        map_count = conn.execute("SELECT COUNT(*) FROM update_map").fetchone()[0]
        if map_count == 0:
            conn.execute("DROP TABLE IF EXISTS chunk_cache; DROP TABLE IF EXISTS update_map;")
            return 0

        conn.execute("""
            UPDATE Geocoding g
            SET geocoding_status = m.target_status,
                last_attempt = CURRENT_TIMESTAMP,
                attempt_count = COALESCE(g.attempt_count, 0) + 1,
                matched_address = CASE
                    WHEN m.target_status LIKE 'grok:%' THEN 'Loaded from geocode_archive (grok failure)'
                    ELSE 'Loaded from geocode_archive (geolocate_prev)'
                END,
                colocator = m.colocator,
                latitude = m.parsed_lat,
                longitude = m.parsed_lon
            FROM update_map m
            WHERE g.geocoding_id = m.geocoding_id
        """)

        # Always fill Addresses from this chunk's geocoding wins (do not leave LL only on Geocoding).
        conn.execute("""
            UPDATE Addresses a
            SET colocator = m.colocator,
                latitude = COALESCE(a.latitude, m.parsed_lat),
                longitude = COALESCE(a.longitude, m.parsed_lon)
            FROM update_map m
            WHERE a.geocoding_id = m.geocoding_id
              AND (a.colocator IS NULL OR TRIM(a.colocator) = '')
        """)

        conn.execute("DROP TABLE IF EXISTS chunk_cache; DROP TABLE IF EXISTS update_map;")
        return map_count

    def finalize_colocators_from_geocoding(self, log_prefix: str = "geolocate") -> None:
        """
        Geocoding → Addresses → owners, then lat/lon + loose_colocator.

        Shared by:
        - FRONT bookend (geolocate_prev) after archive TSV load
        - BACK bookend (geolocate_archive) after census/api/grok, before TSV export

        grant_match reads Grants/Charities.colocator (and loose), not Addresses.
        DOT / address slices read Addresses.colocator.

        Each address_type / owner bucket uses a fresh write-context so OOM on one
        slice cannot leave the shared writer permanently at the memory ceiling.
        """
        log_info(f"[{log_prefix}] Finalizing colocators Geocoding → Addresses → owners + loose")
        print(f"[{log_prefix}] Finalizing colocators from Geocoding...", flush=True)
        self._propagate_colocators_to_owners(conn=None, log_prefix=log_prefix)
        self.populate_lat_lon_and_loose_colocators(log_prefix=log_prefix)

    def _with_fresh_write(self, label: str, fn) -> bool:
        """Run fn(conn) on a fresh write connection; return False on OOM/error (non-fatal)."""
        try:
            with self.db_ops.acquire_write_conn() as conn:
                self._tune_conn(conn)
                fn(conn)
                self._safe_commit(conn, label)
            return True
        except Exception as ex:
            log_warning(f"{label} failed (continuing): {ex}")
            return False

    def _propagate_colocators_to_owners(self, conn=None, log_prefix: str = "geolocate_prev"):
        """
        Propagate colocators: Geocoding → Addresses (if still empty), then Addresses → owners.

        Fresh write connection per slice so one OOM cannot poison the rest of the run.
        Never uses DatabaseOperations.execute_query (sys.exit on OOM).
        """
        log_info("Propagating colocators Geocoding → Addresses → owners...")
        print(f"[{log_prefix}] Geocoding → Addresses colocator fill (by address_type)...", flush=True)

        types = [
            "bmf", "charity", "contractor", "dot_carrier_mail", "dot_carrier_phy",
            "fec_candidate_spending", "fec_committee", "fec_committee_transaction",
            "fec_contributor", "fec_operating_expenditure", "grant",
            "nppes_mailing", "nppes_practice", "ofac_sanction", "officer",
            "politicalcontribution",
        ]
        # Prefer live distinct list when cheap; fall back to static list on OOM.
        def _load_types(c):
            return [
                r[0]
                for r in c.execute(
                    """
                    SELECT DISTINCT address_type FROM Addresses
                    WHERE geocoding_id IS NOT NULL
                    ORDER BY 1
                    """
                ).fetchall()
                if r and r[0]
            ]

        loaded: list = []
        self._with_fresh_write("list_address_types", lambda c: loaded.extend(_load_types(c)))
        if loaded:
            types = loaded

        for at in types:
            def _fill(c, address_type=at):
                print(f"[{log_prefix}]   Addresses fill type={address_type}...", flush=True)
                c.execute(
                    """
                    UPDATE Addresses a
                    SET colocator = g.colocator,
                        latitude = COALESCE(a.latitude, g.latitude),
                        longitude = COALESCE(a.longitude, g.longitude)
                    FROM Geocoding g
                    WHERE a.geocoding_id = g.geocoding_id
                      AND a.address_type = ?
                      AND g.colocator IS NOT NULL AND TRIM(g.colocator) != ''
                      AND (a.colocator IS NULL OR TRIM(a.colocator) = '')
                    """,
                    [address_type],
                )

            self._with_fresh_write(f"addresses_colocator_{at}", _fill)

        print(f"[{log_prefix}] Propagating colocators to owner tables...", flush=True)
        buckets = [f"{i:x}" for i in range(16)]
        for table, id_col, addr_type in [
            ("Charities", "charity_id", "charity"),
            ("Grants", "grant_id", "grant"),
            ("Officers", "officer_id", "officer"),
            ("Contractors", "contractor_id", "contractor"),
            ("PoliticalContributions", "political_id", "politicalcontribution"),
        ]:
            print(f"[{log_prefix}] Owner colocator → {table} (16 buckets)...", flush=True)
            for b in buckets:
                def _owner(c, t=table, ic=id_col, at=addr_type, bucket=b):
                    c.execute(
                        f"""
                        UPDATE {t} t
                        SET colocator = sub.colocator
                        FROM (
                            SELECT a.owner_id,
                                   ANY_VALUE(COALESCE(NULLIF(TRIM(a.colocator), ''), g.colocator)) AS colocator
                            FROM Addresses a
                            INNER JOIN Geocoding g ON a.geocoding_id = g.geocoding_id
                            WHERE a.address_type = '{at}'
                              AND a.owner_id IS NOT NULL
                              AND LOWER(SUBSTR(CAST(a.owner_id AS VARCHAR), 1, 1)) = '{bucket}'
                              AND (
                                    (a.colocator IS NOT NULL AND TRIM(a.colocator) != '')
                                 OR (g.colocator IS NOT NULL AND TRIM(g.colocator) != '')
                              )
                            GROUP BY a.owner_id
                        ) sub
                        WHERE t.{ic} = sub.owner_id
                          AND (t.colocator IS NULL OR t.colocator = '')
                        """
                    )

                self._with_fresh_write(f"{table}_colocator_{b}", _owner)

    def populate_lat_lon_and_loose_colocators(self, log_prefix: str = "geolocate_prev"):
        """
        Backfill lat/lon from colocator, then compute loose_colocator on Addresses + owners.
        Geocoding does not store loose_colocator. Run at front (prev) and back (archive).

        All bulk UPDATEs go through a tuned write connection (no execute_query OOM exit).
        """
        log_info(f"[{log_prefix}] Populating lat/lon + loose_colocator on Addresses/owners...")
        print(f"[{log_prefix}] lat/lon + loose_colocator...", flush=True)

        with self.db_ops.acquire_write_conn() as conn:
            self._tune_conn(conn)
            for ddl in (
                "ALTER TABLE Addresses ADD COLUMN IF NOT EXISTS loose_colocator VARCHAR;",
                "ALTER TABLE Addresses ADD COLUMN IF NOT EXISTS latitude DOUBLE;",
                "ALTER TABLE Addresses ADD COLUMN IF NOT EXISTS longitude DOUBLE;",
            ):
                try:
                    conn.execute(ddl)
                except Exception:
                    pass
            for table in ["Grants", "Charities", "Officers", "Contractors", "PoliticalContributions"]:
                for col_ddl in (
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS lat DOUBLE;",
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS lon DOUBLE;",
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS loose_colocator VARCHAR;",
                ):
                    try:
                        conn.execute(col_ddl)
                    except Exception:
                        pass
            self._safe_commit(conn, "schema_lat_lon")

            for table in ["Grants", "Charities", "Officers", "Contractors", "PoliticalContributions"]:
                self._backfill_lat_lon_for_table_conn(conn, table, log_prefix)

            # Addresses: by address_type
            types = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT address_type FROM Addresses WHERE geocoding_id IS NOT NULL ORDER BY 1"
                ).fetchall()
                if r and r[0]
            ] or ["charity", "grant", "officer", "contractor"]

            for at in types:
                try:
                    print(f"[{log_prefix}] Addresses lat/lon from Geocoding type={at}...", flush=True)
                    conn.execute(
                        """
                        UPDATE Addresses a
                        SET latitude = g.latitude,
                            longitude = g.longitude,
                            colocator = COALESCE(NULLIF(TRIM(a.colocator), ''), g.colocator)
                        FROM Geocoding g
                        WHERE a.geocoding_id = g.geocoding_id
                          AND a.address_type = ?
                          AND g.latitude IS NOT NULL
                          AND a.latitude IS NULL
                        """,
                        [at],
                    )
                    conn.execute(
                        """
                        UPDATE Addresses a
                        SET latitude = TRY_CAST(split_part(g.colocator, ':', 2) AS DOUBLE),
                            longitude = TRY_CAST(split_part(g.colocator, ':', 3) AS DOUBLE),
                            colocator = COALESCE(NULLIF(TRIM(a.colocator), ''), g.colocator)
                        FROM Geocoding g
                        WHERE a.geocoding_id = g.geocoding_id
                          AND a.address_type = ?
                          AND a.latitude IS NULL
                          AND g.colocator LIKE 'LL:%'
                        """,
                        [at],
                    )
                    conn.execute(
                        """
                        UPDATE Addresses
                        SET loose_colocator = 'LL:' || ROUND(latitude / 0.5) * 0.5
                                                  || ':' || ROUND(longitude / 0.5) * 0.5
                        WHERE address_type = ?
                          AND (loose_colocator IS NULL OR TRIM(loose_colocator) = '')
                          AND latitude IS NOT NULL AND longitude IS NOT NULL
                        """,
                        [at],
                    )
                    self._safe_commit(conn, f"addresses_latlon_{at}")
                except Exception as ex:
                    log_warning(f"Addresses lat/lon failed type={at}: {ex}")
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    self._tune_conn(conn)

            for table in ["Grants", "Charities", "Officers", "Contractors", "PoliticalContributions"]:
                try:
                    conn.execute(
                        f"""
                        UPDATE {table}
                        SET loose_colocator = 'LL:' || ROUND(lat / 0.5) * 0.5 || ':' || ROUND(lon / 0.5) * 0.5
                        WHERE (loose_colocator IS NULL OR loose_colocator = '') AND lat IS NOT NULL
                        """
                    )
                    self._safe_commit(conn, f"{table}_loose")
                except Exception as ex:
                    log_warning(f"loose_colocator on {table}: {ex}")
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    self._tune_conn(conn)

            for ddl in (
                "CREATE INDEX IF NOT EXISTS idx_addresses_loose_colocator ON Addresses(loose_colocator);",
                "CREATE INDEX IF NOT EXISTS idx_grants_loose_colocator ON Grants(loose_colocator);",
                "CREATE INDEX IF NOT EXISTS idx_charities_loose_colocator ON Charities(loose_colocator);",
                "CREATE INDEX IF NOT EXISTS idx_grants_lat_lon ON Grants(lat, lon);",
                "CREATE INDEX IF NOT EXISTS idx_charities_lat_lon ON Charities(lat, lon);",
            ):
                try:
                    conn.execute(ddl)
                    self._safe_commit(conn, "index")
                except Exception as ex:
                    log_warning(f"index create: {ex}")

        log_info(f"[{log_prefix}] lat/lon + loose_colocator population complete (Addresses + owners)")

    def _backfill_lat_lon_for_table_conn(self, conn, table: str, log_prefix: str = "geolocate_prev"):
        owner_meta = {
            "Grants": ("grant_id", "grant"),
            "Charities": ("charity_id", "charity"),
            "Officers": ("officer_id", "officer"),
            "Contractors": ("contractor_id", "contractor"),
            "PoliticalContributions": ("political_id", "politicalcontribution"),
        }
        id_col, addr_type = owner_meta[table]
        print(f"[{log_prefix}] lat/lon backfill {table}...", flush=True)
        try:
            conn.execute(
                f"""
                UPDATE {table} t
                SET colocator = COALESCE(NULLIF(t.colocator, ''), sub.colocator)
                FROM (
                    SELECT a.owner_id, ANY_VALUE(g.colocator) AS colocator
                    FROM Addresses a
                    INNER JOIN Geocoding g ON a.geocoding_id = g.geocoding_id
                    WHERE a.address_type = '{addr_type}'
                      AND g.colocator IS NOT NULL
                      AND a.owner_id IS NOT NULL
                    GROUP BY a.owner_id
                ) sub
                WHERE t.{id_col} = sub.owner_id
                  AND (t.colocator IS NULL OR t.colocator = '')
                """
            )
            conn.execute(
                f"""
                UPDATE {table} t
                SET lat = z.lat, lon = z.lon
                FROM Zips z
                WHERE t.colocator LIKE 'PO:%'
                  AND z.zip = split_part(t.colocator, ':', 3)
                  AND t.lat IS NULL
                """
            )
            conn.execute(
                f"""
                UPDATE {table} t
                SET lat = TRY_CAST(split_part(t.colocator, ':', 2) AS DOUBLE),
                    lon = TRY_CAST(split_part(t.colocator, ':', 3) AS DOUBLE)
                WHERE t.colocator LIKE 'LL:%' AND t.lat IS NULL
                """
            )
            conn.execute(
                f"""
                UPDATE {table} t
                SET lat = g.latitude, lon = g.longitude
                FROM Addresses a
                INNER JOIN Geocoding g ON a.geocoding_id = g.geocoding_id
                WHERE t.{id_col} = a.owner_id
                  AND a.address_type = '{addr_type}'
                  AND t.lat IS NULL
                  AND g.latitude IS NOT NULL
                """
            )
            self._safe_commit(conn, f"{table}_latlon")
        except Exception as ex:
            log_warning(f"lat/lon backfill {table}: {ex}")
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            self._tune_conn(conn)

    def _backfill_lat_lon_for_table(self, table: str):
        """Legacy entry — opens its own write conn (prefer _backfill_lat_lon_for_table_conn)."""
        with self.db_ops.acquire_write_conn() as conn:
            self._tune_conn(conn)
            self._backfill_lat_lon_for_table_conn(conn, table)
