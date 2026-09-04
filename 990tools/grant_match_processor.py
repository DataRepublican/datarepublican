#!/usr/bin/env python3
"""
grant_match_processor.py - Processor for matching grants to charities
"""

from typing import List, Dict, Any, Tuple, Optional
import queue
import re
import os
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from logging_utils import log_info, log_debug
from config import global_config
from base_processor import BaseProcessor, WorkUnit
from pending_database_context import PendingDatabaseContext
from collections import defaultdict
from countryCodes import iso3166_alpha2  # ← from your generate_foreign_update.py
from models import AuthoritativeEin
import hashlib

# EINless integration (per 2026-06 hygiene "we're done... tie this off in a bow" review + architect plan):
# einless/ (with pass_through_flow, foreign_synthetic, grantor-context assigned_ein from the by_dollars hygiene
# hard 125404 after flow patterns) provides pre-classified buckets for early handling in grant matching.
# Use _hard_flow.tsv / _hard_foreign.tsv / the pass_through_flow flag on hard to apply "A passes to B" logic,
# grantor attribution for foreign grantees of US foundations, and avoid forcing recipient EINs on structural tail.
# See einless/ structure (A), pipeline.py, and einless/docs/..._architecture.md for the full integration sketch
# (unifies with the pre-phonebook complicated rules in generate_name_rules.py for canonical rollups + secondary geo).
# This complements the core phonebook cream (~89% honest) and the big_pharma/foreign early exits already here.

COMPANY_SUFFIX_REGEX = re.compile(r'\\s+(INC|CORP|LLC|FOUNDATION|MINISTRY|ASSOCIATION|CHURCH)$', re.IGNORECASE)
    
def word_jaccard(name1: str, name2: str) -> float:
    """Compute Jaccard similarity on word sets"""
    if not name1 or not name2:
        return 0.0
    if name1.lower() == name2.lower():
        return 1.0
    cleaned1 = COMPANY_SUFFIX_REGEX.sub('', name1.lower()).strip()
    cleaned2 = COMPANY_SUFFIX_REGEX.sub('', name2.lower()).strip()
    if cleaned1 == cleaned2:
        return 1.0
    words1 = set(cleaned1.lower().split())
    words2 = set(cleaned2.lower().split())
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    return intersection / union if union else 0.0

class GrantMatchProcessor(BaseProcessor):
    """Processor for matching grants to charities"""

    def __init__(self, db_ops: DatabaseOperations):
        super().__init__(db_ops)
        self.batch_size = 1000
        self.jaccard_threshold = 0.7
        self.distance_km = 40.23  # 25 mi in km
    
    def match_grants(self) -> int:
        """Run the grant matching process"""

        # Heal corrupted Grants primary ART index if UPDATEs are fatal (DuckDB ART bug).
        self.ensure_grants_writable()
        # Same ART class of bug hits Charities on large lat/lon UPDATEs.
        self.ensure_charities_writable()

        # === VERY FIRST STEP: Foreign EINs ===
        self.apply_foreign_eins()
        self.build_zips_table()

        # === NEW STEP #1: lat/lon population (idempotent; CTAS-safe) ===
        self.populate_lat_lon_columns()

        # === Tier 1-3 initialization (only if needed) ===
        table_exists = self.db_ops.execute_query(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='AuthoritativeEin'"
        ).fetchone() is not None

        has_rows = False
        if table_exists:
            has_rows = self.db_ops.execute_query(
                "SELECT 1 FROM AuthoritativeEin LIMIT 1"
            ).fetchone() is not None

        if not table_exists or not has_rows:
            log_info("AuthoritativeEin table missing or empty → running full initialization")
            self.build_authoritative_ein_table()
            self.mass_pre_match_exact_colocator()
            self.mass_pre_match_loose_colocator()
        else:
            log_info("AuthoritativeEin table exists → skipping rebuild / mass pre-match")

        # GIN for remaining floating (colocator-null) grants — always, idempotent
        self.backfill_gins_for_remaining_floating()

        # === Tier 4: Parallel matching on remaining loose grants ===
        processed = self.process_parallel(global_config.max_files, global_config.workers)

        return processed

    def ensure_grants_writable(self) -> None:
        """
        Probe Grants UPDATE. If PRIMARY ART index is corrupt, rebuild via CTAS.
        Uses the app pool connection (must share DuckDB config with open handles).
        """
        log_info("Probing Grants writability (PRIMARY ART health)...")
        try:
            self.db_ops.execute_query("""
                UPDATE Grants SET recipient_ein = recipient_ein
                WHERE grant_id = (SELECT grant_id FROM Grants LIMIT 1)
            """)
            log_info("Grants UPDATE probe OK")
            return
        except Exception as e:
            msg = str(e)
            log_info(f"Grants probe result: {e}")
            if "PRIMARY_Grants" not in msg and "gated leaf" not in msg and "Corrupted unique ART" not in msg:
                log_info("Non-ART probe failure — continuing without rebuild")
                return

        log_info("Grants PRIMARY ART corrupt — rebuilding table")
        # Pool write conn is likely invalidated after FATAL; reconnect before CTAS.
        try:
            pool = type(self.db_ops).get_pool()
            if pool is not None and getattr(pool, "write_conn", None) is not None:
                try:
                    pool.write_conn.close()
                except Exception:
                    pass
                pool.write_conn = pool._new_conn(read_only=False)
                log_info("Reconnected pool write connection after ART fatal")
        except Exception as recon_e:
            log_info(f"Write reconnect note: {recon_e}")

        self.rebuild_grants_table(reason="heal corrupted PRIMARY_Grants ART index")

    def rebuild_grants_table(self, reason: str = "") -> None:
        """Copy Grants → drop → rename; recreate PK + secondary indexes. Expensive but safe."""
        log_info(f"Rebuilding Grants table ({reason or 'no reason'})...")
        print(f"[grant_match] Rebuilding Grants table: {reason}", flush=True)

        # Fresh write path — CTAS copies heap without broken ART leaf state
        self.db_ops.execute_query("DROP TABLE IF EXISTS Grants_rebuild")
        self.db_ops.execute_query("""
            CREATE TABLE Grants_rebuild AS
            SELECT * FROM Grants
        """)
        count = self.db_ops.execute_query("SELECT COUNT(*) FROM Grants_rebuild").fetchone()[0]
        log_info(f"Grants_rebuild has {count:,} rows — swapping")
        print(f"[grant_match] Grants_rebuild rows={count:,}; swapping", flush=True)

        self.db_ops.execute_query("DROP TABLE Grants")
        self.db_ops.execute_query("ALTER TABLE Grants_rebuild RENAME TO Grants")

        # Primary key (unique ART rebuilt clean)
        try:
            self.db_ops.execute_query("ALTER TABLE Grants ADD PRIMARY KEY (grant_id)")
        except Exception as e:
            log_info(f"ADD PRIMARY KEY failed ({e}); using UNIQUE INDEX fallback")
            self.db_ops.execute_query(
                "CREATE UNIQUE INDEX IF NOT EXISTS PRIMARY_Grants_0 ON Grants(grant_id)"
            )

        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_grants_filer_ein ON Grants(filer_ein)",
            "CREATE INDEX IF NOT EXISTS idx_grants_recipient_ein ON Grants(recipient_ein)",
            "CREATE INDEX IF NOT EXISTS idx_grants_tax_year ON Grants(tax_year)",
            "CREATE INDEX IF NOT EXISTS idx_grants_colocator ON Grants(colocator)",
            "CREATE INDEX IF NOT EXISTS idx_grants_filer_colocator ON Grants(filer_colocator)",
            "CREATE INDEX IF NOT EXISTS idx_grants_loose_colocator ON Grants(loose_colocator)",
            "CREATE INDEX IF NOT EXISTS idx_grants_grant_id ON Grants(grant_id)",
            "CREATE INDEX IF NOT EXISTS idx_grants_lat ON Grants(lat)",
            "CREATE INDEX IF NOT EXISTS idx_grants_lon ON Grants(lon)",
            "CREATE INDEX IF NOT EXISTS idx_grant_backfill_ein ON Grants(recipient_ein_backfilled)",
            "CREATE INDEX IF NOT EXISTS idx_grant_bmf_name ON Grants(grantee_name_bmf)",
            "CREATE INDEX IF NOT EXISTS idx_grant_geo_name ON Grants(grantee_name_geo)",
        ):
            try:
                self.db_ops.execute_query(ddl)
            except Exception as e:
                log_info(f"Index recreate skipped/failed: {ddl[:60]}… ({e})")

        try:
            self.db_ops.execute_query("CHECKPOINT")
        except Exception:
            pass

        # Re-probe
        self.db_ops.execute_query("""
            UPDATE Grants SET recipient_ein = recipient_ein
            WHERE grant_id = (SELECT grant_id FROM Grants LIMIT 1)
        """)
        log_info("Grants table rebuild complete — UPDATE probe OK")
        print("[grant_match] Grants rebuild complete", flush=True)

    def ensure_charities_writable(self) -> None:
        """Probe Charities UPDATE; rebuild via CTAS if PRIMARY ART is corrupt."""
        log_info("Probing Charities writability (PRIMARY ART health)...")
        try:
            self.db_ops.execute_query("""
                UPDATE Charities SET lat = lat
                WHERE charity_id = (SELECT charity_id FROM Charities LIMIT 1)
            """)
            log_info("Charities UPDATE probe OK")
            return
        except Exception as e:
            msg = str(e)
            log_info(f"Charities probe result: {e}")
            if "PRIMARY_Charit" not in msg and "Charities_" not in msg and "gated leaf" not in msg and "Corrupted unique ART" not in msg:
                log_info("Non-ART Charities probe failure — continuing without rebuild")
                return

        log_info("Charities PRIMARY ART corrupt — rebuilding table")
        try:
            pool = type(self.db_ops).get_pool()
            if pool is not None and getattr(pool, "write_conn", None) is not None:
                try:
                    pool.write_conn.close()
                except Exception:
                    pass
                pool.write_conn = pool._new_conn(read_only=False)
                log_info("Reconnected pool write connection after Charities ART fatal")
        except Exception as recon_e:
            log_info(f"Write reconnect note: {recon_e}")

        self.rebuild_charities_table(reason="heal corrupted PRIMARY_Charities ART index")

    def rebuild_charities_table(self, reason: str = "") -> None:
        """Copy Charities → drop → rename; recreate PK + secondary indexes."""
        log_info(f"Rebuilding Charities table ({reason or 'no reason'})...")
        print(f"[grant_match] Rebuilding Charities table: {reason}", flush=True)

        self.db_ops.execute_query("DROP TABLE IF EXISTS Charities_rebuild")
        self.db_ops.execute_query("CREATE TABLE Charities_rebuild AS SELECT * FROM Charities")
        count = self.db_ops.execute_query("SELECT COUNT(*) FROM Charities_rebuild").fetchone()[0]
        log_info(f"Charities_rebuild has {count:,} rows — swapping")
        print(f"[grant_match] Charities_rebuild rows={count:,}; swapping", flush=True)

        self.db_ops.execute_query("DROP TABLE Charities")
        self.db_ops.execute_query("ALTER TABLE Charities_rebuild RENAME TO Charities")

        try:
            self.db_ops.execute_query("ALTER TABLE Charities ADD PRIMARY KEY (charity_id)")
        except Exception as e:
            log_info(f"ADD PRIMARY KEY failed ({e}); using UNIQUE INDEX fallback")
            self.db_ops.execute_query(
                "CREATE UNIQUE INDEX IF NOT EXISTS PRIMARY_Charities_0 ON Charities(charity_id)"
            )

        for ddl in (
            "CREATE UNIQUE INDEX IF NOT EXISTS Charities_xml_name_key ON Charities(xml_name)",
            "CREATE INDEX IF NOT EXISTS idx_charities_colocator ON Charities(colocator)",
            "CREATE INDEX IF NOT EXISTS idx_charities_denominator ON Charities(denominator)",
            "CREATE INDEX IF NOT EXISTS idx_charities_ein ON Charities(ein)",
            "CREATE INDEX IF NOT EXISTS idx_charities_form_type ON Charities(form_type)",
            "CREATE INDEX IF NOT EXISTS idx_charities_lat ON Charities(lat)",
            "CREATE INDEX IF NOT EXISTS idx_charities_lon ON Charities(lon)",
            "CREATE INDEX IF NOT EXISTS idx_charities_loose_colocator ON Charities(loose_colocator)",
            "CREATE INDEX IF NOT EXISTS idx_charities_org_type ON Charities(org_type)",
            "CREATE INDEX IF NOT EXISTS idx_charities_tax_year ON Charities(tax_year)",
        ):
            try:
                self.db_ops.execute_query(ddl)
            except Exception as e:
                log_info(f"Index recreate skipped/failed: {ddl[:60]}… ({e})")

        try:
            self.db_ops.execute_query("CHECKPOINT")
        except Exception:
            pass

        self.db_ops.execute_query("""
            UPDATE Charities SET lat = lat
            WHERE charity_id = (SELECT charity_id FROM Charities LIMIT 1)
        """)
        log_info("Charities table rebuild complete — UPDATE probe OK")
        print("[grant_match] Charities rebuild complete", flush=True)

    def apply_foreign_eins(self):
        """Foreign EINs as the very first step. Updates Grants + populates Backfill."""
        log_info("Applying foreign EINs from country codes...")

        for iso, data in iso3166_alpha2.items():
            ein = data["number"]
            conditions = [f"colocator = 'FA:{iso}'"]
            # Add FIPS variants if any
            # (your original script logic)
            update_sql = f"""
            UPDATE Grants 
            SET recipient_ein = '{ein}'
            WHERE { ' OR '.join(conditions) };
            """
            self.db_ops.execute_query(update_sql)

            # Also populate Backfill
            insert_sql = """
            INSERT INTO Backfill (recipient_ein, name, source)
            SELECT DISTINCT ?, grantee_name, 'foreign'
            FROM Grants 
            WHERE recipient_ein = ? 
            ON CONFLICT (recipient_ein) DO NOTHING
            """
            self.db_ops.execute_query(insert_sql, [ein, ein])

        log_info("Foreign EINs applied and Backfill populated")

    def build_authoritative_ein_table(self):
        """Rebuild AuthoritativeEin with BOTH colocator and loose_colocator."""
        log_info("Rebuilding AuthoritativeEin with colocator + loose_colocator...")

        self.db_ops.execute_query("DROP TABLE IF EXISTS AuthoritativeEin;")

        self.db_ops.execute_query("""
        CREATE TABLE AuthoritativeEin (
            name            VARCHAR NOT NULL,
            colocator       VARCHAR,           -- exact original
            loose_colocator VARCHAR,           -- 0.5° grid
            ein             VARCHAR(9) NOT NULL,
            count           INTEGER,
            PRIMARY KEY (name, colocator, loose_colocator)
        );
        """)

        self.db_ops.execute_query("""
        CREATE INDEX idx_an_name_colocator ON AuthoritativeEin(name, colocator);
        CREATE INDEX idx_an_name_loose     ON AuthoritativeEin(name, loose_colocator);
        """)

        # Global rows (most common EIN per name)
        self.db_ops.execute_query("""
        INSERT INTO AuthoritativeEin (name, colocator, loose_colocator, ein, count)
        WITH ranked AS (
            SELECT grantee_name, recipient_ein, COUNT(*) AS cnt,
                   ROW_NUMBER() OVER (PARTITION BY grantee_name ORDER BY COUNT(*) DESC) AS rn
            FROM Grants
            WHERE recipient_ein IS NOT NULL 
              AND recipient_ein != '8686'
              AND recipient_ein NOT LIKE '70%'
            GROUP BY grantee_name, recipient_ein
        )
        SELECT grantee_name, 'NULL', 'NULL', recipient_ein, cnt
        FROM ranked WHERE rn = 1;
        """)

        # Specific rows — both exact and loose
        self.db_ops.execute_query("""
        INSERT INTO AuthoritativeEin (name, colocator, loose_colocator, ein, count)
        WITH ranked AS (
            SELECT grantee_name, colocator, loose_colocator, recipient_ein, COUNT(*) AS cnt,
                   ROW_NUMBER() OVER (PARTITION BY grantee_name, colocator, loose_colocator 
                                      ORDER BY COUNT(*) DESC) AS rn
            FROM Grants
            WHERE recipient_ein IS NOT NULL 
              AND recipient_ein != '8686'
              AND recipient_ein NOT LIKE '70%'
              AND (colocator IS NOT NULL AND loose_colocator IS NOT NULL)
            GROUP BY grantee_name, colocator, loose_colocator, recipient_ein
        )
        SELECT grantee_name, colocator, loose_colocator, recipient_ein, cnt
        FROM ranked WHERE rn = 1;
        """)

        log_info("AuthoritativeEin rebuilt with both colocator and loose_colocator")

    def mass_pre_match_exact_colocator(self):
        """First pass: exact colocator match (best case)."""
        self.db_ops.execute_query("""
        UPDATE Grants g
        SET recipient_ein = a.ein
        FROM AuthoritativeEin a
        WHERE g.grantee_name = a.name
          AND g.colocator = a.colocator
          AND (g.recipient_ein IS NULL OR g.recipient_ein = '8686');
        """)
        log_info("Mass pre-match on exact colocator complete")

    def mass_pre_match_loose_colocator(self):
        """Second pass: loose_colocator match (weeds)."""
        self.db_ops.execute_query("""
        UPDATE Grants g
        SET recipient_ein = a.ein
        FROM AuthoritativeEin a
        WHERE g.grantee_name = a.name
          AND g.loose_colocator = a.loose_colocator
          AND (g.recipient_ein IS NULL OR g.recipient_ein = '8686');
        """)
        log_info("Mass pre-match on loose_colocator complete")

    def backfill_gins_for_remaining_floating(self):
        """
        GINs for remaining floating grants (no colocator) using full SHA256.

        Avoids one giant JOIN UPDATE on Grants (corrupts DuckDB PRIMARY ART under load).
        Uses name→GIN map + batched grant_id updates, falling back to CTAS rebuild.
        """
        log_info("GIN backfill for floating grants (no colocator or BOGUS:)...")
        print("[grant_match] GIN backfill starting...", flush=True)

        floating = self.db_ops.execute_query("""
            SELECT COUNT(*) FROM Grants
            WHERE (recipient_ein IS NULL OR recipient_ein = '8686')
              AND (colocator IS NULL OR colocator LIKE 'BOGUS:%')
        """).fetchone()[0]
        log_info(f"Floating grants needing GIN: {floating:,}")
        if floating == 0:
            log_info("No floating grants for GIN — skip")
            return

        try:
            self.db_ops.execute_query("DROP INDEX IF EXISTS idx_backfill_recipient_ein")
        except Exception:
            pass
        try:
            self.db_ops.execute_query(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_backfill_recipient_ein ON Backfill (recipient_ein)"
            )
        except Exception as e:
            log_info(f"Backfill unique index note: {e}")

        self.db_ops.execute_query("DROP TABLE IF EXISTS temp_gins")
        self.db_ops.execute_query("""
            CREATE TABLE temp_gins AS
            SELECT DISTINCT
                g.grantee_name,
                '70' || HEX(SHA256(
                    UPPER(TRIM(REGEXP_REPLACE(
                        g.grantee_name,
                        '\\s+(INC|CORP|LLC|FOUNDATION|MINISTRY|ASSOCIATION|CHURCH)$',
                        '', 'gi'
                    )))
                )) AS generated_gin
            FROM Grants g
            WHERE (g.recipient_ein IS NULL OR g.recipient_ein = '8686')
              AND (g.colocator IS NULL OR g.colocator LIKE 'BOGUS:%')
        """)
        n_names = self.db_ops.execute_query("SELECT COUNT(*) FROM temp_gins").fetchone()[0]
        log_info(f"temp_gins distinct names: {n_names:,}")

        self.db_ops.execute_query("""
            INSERT INTO Backfill (recipient_ein, name, source)
            SELECT generated_gin, grantee_name, 'gin'
            FROM temp_gins
            ON CONFLICT (recipient_ein) DO NOTHING
        """)

        # Large floating sets: CTAS rebuild (avoids ART corruption + avoids N× join-LIMIT thrash).
        # Small sets: single UPDATE is fine after PRIMARY heal.
        applied = floating
        if floating >= 100_000:
            log_info(f"GIN CTAS rebuild path ({floating:,} floating grants)...")
            print(f"[grant_match] GIN CTAS rebuild for {floating:,} rows...", flush=True)
            self.db_ops.execute_query("DROP TABLE IF EXISTS Grants_rebuild")
            self.db_ops.execute_query("""
                CREATE TABLE Grants_rebuild AS
                SELECT
                    g.grant_id,
                    g.filer_ein,
                    g.filer_name,
                    g.grantee_name,
                    g.grantee_sndx,
                    CASE
                        WHEN (g.recipient_ein IS NULL OR g.recipient_ein = '8686')
                             AND (g.colocator IS NULL OR g.colocator LIKE 'BOGUS:%')
                             AND t.generated_gin IS NOT NULL
                        THEN t.generated_gin
                        ELSE g.recipient_ein
                    END AS recipient_ein,
                    g.grant_amt,
                    g.tax_year,
                    g.colocator,
                    g.filer_colocator,
                    g.created_at,
                    g.recipient_ein_backfilled,
                    g.grantee_name_bmf,
                    g.grantee_name_geo,
                    g.grantee_name_conc,
                    g.lat,
                    g.lon,
                    g.loose_colocator
                FROM Grants g
                LEFT JOIN temp_gins t
                  ON g.grantee_name = t.grantee_name
                 AND (g.colocator IS NULL OR g.colocator LIKE 'BOGUS:%')
                 AND (g.recipient_ein IS NULL OR g.recipient_ein = '8686')
            """)
            n_new = self.db_ops.execute_query("SELECT COUNT(*) FROM Grants_rebuild").fetchone()[0]
            log_info(f"Grants_rebuild rows={n_new:,}; swapping")
            self.db_ops.execute_query("DROP TABLE Grants")
            self.db_ops.execute_query("ALTER TABLE Grants_rebuild RENAME TO Grants")
            try:
                self.db_ops.execute_query("ALTER TABLE Grants ADD PRIMARY KEY (grant_id)")
            except Exception:
                self.db_ops.execute_query(
                    "CREATE UNIQUE INDEX IF NOT EXISTS PRIMARY_Grants_0 ON Grants(grant_id)"
                )
            for ddl in (
                "CREATE INDEX IF NOT EXISTS idx_grants_filer_ein ON Grants(filer_ein)",
                "CREATE INDEX IF NOT EXISTS idx_grants_recipient_ein ON Grants(recipient_ein)",
                "CREATE INDEX IF NOT EXISTS idx_grants_tax_year ON Grants(tax_year)",
                "CREATE INDEX IF NOT EXISTS idx_grants_colocator ON Grants(colocator)",
                "CREATE INDEX IF NOT EXISTS idx_grants_filer_colocator ON Grants(filer_colocator)",
                "CREATE INDEX IF NOT EXISTS idx_grants_loose_colocator ON Grants(loose_colocator)",
                "CREATE INDEX IF NOT EXISTS idx_grants_grant_id ON Grants(grant_id)",
                "CREATE INDEX IF NOT EXISTS idx_grants_lat ON Grants(lat)",
                "CREATE INDEX IF NOT EXISTS idx_grants_lon ON Grants(lon)",
            ):
                try:
                    self.db_ops.execute_query(ddl)
                except Exception:
                    pass
            try:
                self.db_ops.execute_query("CHECKPOINT")
            except Exception:
                pass
        else:
            log_info(f"GIN single UPDATE path ({floating:,} floating)...")
            self.db_ops.execute_query("""
                UPDATE Grants g
                SET recipient_ein = t.generated_gin
                FROM temp_gins t
                WHERE g.grantee_name = t.grantee_name
                  AND (g.colocator IS NULL OR g.colocator LIKE 'BOGUS:%')
                  AND (g.recipient_ein IS NULL OR g.recipient_ein = '8686')
            """)

        self.db_ops.execute_query("DROP TABLE IF EXISTS temp_gins")
        remaining = self.db_ops.execute_query("""
            SELECT COUNT(*) FROM Grants
            WHERE (recipient_ein IS NULL OR recipient_ein = '8686')
              AND (colocator IS NULL OR colocator LIKE 'BOGUS:%')
        """).fetchone()[0]
        log_info(
            f"GIN backfill done — target ~{applied:,}; floating remaining {remaining:,}"
        )
        print(
            f"[grant_match] GIN done target~{applied:,} floating_left={remaining:,}",
            flush=True,
        )

    def build_zips_table(self):
        """Build the Zips table from US_zips.txt.gz (12 columns, deduplicate on zip)."""
        log_info("Building Zips table from US_zips.txt.gz...")

        # Build path relative to current working directory
        zip_file_path = os.path.join(os.getcwd(), "US_zips.txt.gz")

        # Drop and recreate clean Zips table
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
            lat       DOUBLE,
            lon      DOUBLE,
            accuracy       INTEGER
        );
        """)

        # Step 1: Load raw data into temp table
        self.db_ops.execute_query(f"""
        CREATE TEMP TABLE zips_raw AS
        SELECT * FROM read_csv_auto('{zip_file_path}',
            delim = '\t',
            header = false,
            columns = {{
                'country_code': 'VARCHAR',
                'zip': 'VARCHAR',
                'place_name': 'VARCHAR',
                'state_name': 'VARCHAR',
                'state_code': 'VARCHAR',
                'region_name': 'VARCHAR',
                'region_code': 'VARCHAR',
                'extra1': 'VARCHAR',
                'extra2': 'VARCHAR',
                'lat': 'DOUBLE',
                'lon': 'DOUBLE',
                'accuracy': 'INTEGER'
            }}
        );
        """)

        # Step 2: Insert into final table with deduplication (first row per zip wins)
        self.db_ops.execute_query("""
        INSERT INTO Zips
        SELECT 
            country_code,
            zip,
            place_name,
            state_name,
            state_code,
            region_name,
            region_code,
            extra1,
            extra2,
            lat,
            lon,
            accuracy
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY zip ORDER BY 1) AS rn  -- first row per zip
            FROM zips_raw
        ) t
        WHERE rn = 1;
        """)

        self.db_ops.execute_query("""
        CREATE INDEX idx_zips_zip ON Zips(zip);
        """)

        self.db_ops.execute_query("DROP TABLE IF EXISTS zips_raw;")

        count = self.db_ops.execute_query("SELECT COUNT(*) FROM Zips").fetchone()[0]
        log_info(f"Zips table built successfully — {count:,} unique zip codes loaded")

        self.db_ops.execute_query("CREATE INDEX IF NOT EXISTS idx_zips_zip ON Zips(zip);")
        
    def populate_lat_lon_columns(self):
        """Step #1: Add and populate lat/lon columns on Grants and Charities.

        Always fills rows still missing lat (idempotent via ``lat IS NULL`` guards).
        PO zips missing from Zips are marked ``BOGUS:{zip5}`` so they exit the
        geo-match work set (same convention as geocoding_api_processor).

        Implementation note: large in-place UPDATEs against DuckDB unique ART
        indexes have repeatedly FATAL'd (PRIMARY_Grants / PRIMARY_Charities
        duplicate-key on commit). Fill via CTAS rebuild instead — same end
        state, no mid-index delete/reinsert thrash.
        """
        log_info("Populating lat/lon columns via CTAS (ART-safe)...")

        # Add columns if missing (no-op once present)
        self.db_ops.execute_query("ALTER TABLE Grants ADD COLUMN IF NOT EXISTS lat DOUBLE;")
        self.db_ops.execute_query("ALTER TABLE Grants ADD COLUMN IF NOT EXISTS lon DOUBLE;")
        self.db_ops.execute_query("ALTER TABLE Charities ADD COLUMN IF NOT EXISTS lat DOUBLE;")
        self.db_ops.execute_query("ALTER TABLE Charities ADD COLUMN IF NOT EXISTS lon DOUBLE;")

        # --- Grants: equality-join path (no LIKE nested-loop against Zips) ---
        # 1) extract zip/LL keys for null-lat rows only
        # 2) hash-join Zips on zip equality → lat map
        # 3) CTAS Grants LEFT JOIN map ON grant_id (hash join)
        log_info("Grants lat/lon equality-join fill...")
        print("[grant_match] Grants lat/lon equality-join fill", flush=True)
        self.db_ops.execute_query("DROP TABLE IF EXISTS _grant_zip_keys")
        self.db_ops.execute_query("DROP TABLE IF EXISTS _grant_lat_map")
        self.db_ops.execute_query("DROP TABLE IF EXISTS Grants_latfill")

        self.db_ops.execute_query("""
        CREATE TABLE _grant_zip_keys AS
        SELECT
            grant_id,
            colocator,
            recipient_ein,
            CASE
                WHEN colocator LIKE 'LL:%'
                    THEN TRY_CAST(split_part(colocator, ':', 2) AS DOUBLE)
                ELSE NULL
            END AS ll_lat,
            CASE
                WHEN colocator LIKE 'LL:%'
                    THEN TRY_CAST(split_part(colocator, ':', 3) AS DOUBLE)
                ELSE NULL
            END AS ll_lon,
            CASE
                WHEN colocator LIKE 'PO:%' THEN split_part(colocator, ':', 3)
                WHEN colocator LIKE 'MULTI:%' THEN split_part(colocator, ':', -1)
                WHEN colocator LIKE 'PRIV:%'
                  OR colocator LIKE 'MALL:%'
                  OR colocator LIKE 'MAJOR:%' THEN split_part(colocator, ':', -1)
                ELSE NULL
            END AS zip5,
            CASE
                WHEN colocator LIKE 'PO:%'
                  OR colocator LIKE 'MULTI:%'
                  OR colocator LIKE 'PRIV:%' THEN true
                ELSE false
            END AS bogus_candidate
        FROM Grants
        WHERE lat IS NULL
          AND colocator IS NOT NULL
        """)
        self.db_ops.execute_query(
            "CREATE INDEX IF NOT EXISTS idx_gzk_zip ON _grant_zip_keys(zip5)"
        )

        self.db_ops.execute_query("""
        CREATE TABLE _grant_lat_map AS
        SELECT
            k.grant_id,
            COALESCE(k.ll_lat, z.lat) AS lat,
            COALESCE(k.ll_lon, z.lon) AS lon,
            k.colocator,
            k.recipient_ein,
            k.bogus_candidate
        FROM _grant_zip_keys k
        LEFT JOIN Zips z ON z.zip = k.zip5
        """)
        self.db_ops.execute_query(
            "CREATE INDEX IF NOT EXISTS idx_glm_gid ON _grant_lat_map(grant_id)"
        )
        mapped = self.db_ops.execute_query(
            "SELECT COUNT(*) FILTER (WHERE lat IS NOT NULL) FROM _grant_lat_map"
        ).fetchone()[0]
        log_info(f"Grants lat map: {mapped:,} rows with coords")
        print(f"[grant_match] Grants lat map coords={mapped:,}", flush=True)

        self.db_ops.execute_query("""
        CREATE TABLE Grants_latfill AS
        SELECT
            g.* EXCLUDE (lat, lon, loose_colocator, colocator),
            COALESCE(g.lat, m.lat) AS lat,
            COALESCE(g.lon, m.lon) AS lon,
            CASE
                WHEN g.loose_colocator IS NOT NULL THEN g.loose_colocator
                WHEN COALESCE(g.lat, m.lat) IS NOT NULL THEN
                    'LL:' || ROUND(COALESCE(g.lat, m.lat) / 0.5) * 0.5
                    || ':' || ROUND(COALESCE(g.lon, m.lon) / 0.5) * 0.5
                ELSE g.loose_colocator
            END AS loose_colocator,
            CASE
                WHEN m.bogus_candidate
                 AND g.lat IS NULL
                 AND m.lat IS NULL
                 AND m.recipient_ein IS NULL
                 AND g.colocator NOT LIKE 'BOGUS:%'
                THEN 'BOGUS:' || COALESCE(NULLIF(split_part(g.colocator, ':', -1), ''), '00000')
                ELSE g.colocator
            END AS colocator
        FROM Grants g
        LEFT JOIN _grant_lat_map m ON g.grant_id = m.grant_id
        """)
        gcount = self.db_ops.execute_query("SELECT COUNT(*) FROM Grants_latfill").fetchone()[0]
        log_info(f"Grants_latfill rows={gcount:,} — swapping")
        self.db_ops.execute_query("DROP TABLE Grants")
        self.db_ops.execute_query("ALTER TABLE Grants_latfill RENAME TO Grants")
        self.db_ops.execute_query("DROP TABLE IF EXISTS _grant_zip_keys")
        self.db_ops.execute_query("DROP TABLE IF EXISTS _grant_lat_map")
        try:
            self.db_ops.execute_query("ALTER TABLE Grants ADD PRIMARY KEY (grant_id)")
        except Exception as e:
            log_info(f"Grants ADD PRIMARY KEY failed ({e}); UNIQUE INDEX fallback")
            self.db_ops.execute_query(
                "CREATE UNIQUE INDEX IF NOT EXISTS PRIMARY_Grants_0 ON Grants(grant_id)"
            )
        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_grants_filer_ein ON Grants(filer_ein)",
            "CREATE INDEX IF NOT EXISTS idx_grants_recipient_ein ON Grants(recipient_ein)",
            "CREATE INDEX IF NOT EXISTS idx_grants_tax_year ON Grants(tax_year)",
            "CREATE INDEX IF NOT EXISTS idx_grants_colocator ON Grants(colocator)",
            "CREATE INDEX IF NOT EXISTS idx_grants_filer_colocator ON Grants(filer_colocator)",
            "CREATE INDEX IF NOT EXISTS idx_grants_loose_colocator ON Grants(loose_colocator)",
            "CREATE INDEX IF NOT EXISTS idx_grants_grant_id ON Grants(grant_id)",
            "CREATE INDEX IF NOT EXISTS idx_grants_lat ON Grants(lat)",
            "CREATE INDEX IF NOT EXISTS idx_grants_lon ON Grants(lon)",
            "CREATE INDEX IF NOT EXISTS idx_grant_backfill_ein ON Grants(recipient_ein_backfilled)",
            "CREATE INDEX IF NOT EXISTS idx_grant_bmf_name ON Grants(grantee_name_bmf)",
            "CREATE INDEX IF NOT EXISTS idx_grant_geo_name ON Grants(grantee_name_geo)",
        ):
            try:
                self.db_ops.execute_query(ddl)
            except Exception as e:
                log_info(f"Grants index recreate skipped: {ddl[:50]}… ({e})")

        # --- Charities: same equality-join pattern ---
        log_info("Charities lat/lon equality-join fill...")
        print("[grant_match] Charities lat/lon equality-join fill", flush=True)
        self.db_ops.execute_query("DROP TABLE IF EXISTS _charity_zip_keys")
        self.db_ops.execute_query("DROP TABLE IF EXISTS _charity_lat_map")
        self.db_ops.execute_query("DROP TABLE IF EXISTS Charities_latfill")

        self.db_ops.execute_query("""
        CREATE TABLE _charity_zip_keys AS
        SELECT
            charity_id,
            CASE
                WHEN colocator LIKE 'LL:%'
                    THEN TRY_CAST(split_part(colocator, ':', 2) AS DOUBLE)
                ELSE NULL
            END AS ll_lat,
            CASE
                WHEN colocator LIKE 'LL:%'
                    THEN TRY_CAST(split_part(colocator, ':', 3) AS DOUBLE)
                ELSE NULL
            END AS ll_lon,
            CASE
                WHEN colocator LIKE 'PO:%' THEN split_part(colocator, ':', 3)
                ELSE NULL
            END AS zip5
        FROM Charities
        WHERE lat IS NULL
          AND colocator IS NOT NULL
        """)
        self.db_ops.execute_query(
            "CREATE INDEX IF NOT EXISTS idx_czk_zip ON _charity_zip_keys(zip5)"
        )
        self.db_ops.execute_query("""
        CREATE TABLE _charity_lat_map AS
        SELECT
            k.charity_id,
            COALESCE(k.ll_lat, z.lat) AS lat,
            COALESCE(k.ll_lon, z.lon) AS lon
        FROM _charity_zip_keys k
        LEFT JOIN Zips z ON z.zip = k.zip5
        """)
        self.db_ops.execute_query(
            "CREATE INDEX IF NOT EXISTS idx_clm_cid ON _charity_lat_map(charity_id)"
        )

        self.db_ops.execute_query("""
        CREATE TABLE Charities_latfill AS
        SELECT
            c.* EXCLUDE (lat, lon, loose_colocator),
            COALESCE(c.lat, m.lat) AS lat,
            COALESCE(c.lon, m.lon) AS lon,
            CASE
                WHEN c.loose_colocator IS NOT NULL THEN c.loose_colocator
                WHEN COALESCE(c.lat, m.lat) IS NOT NULL THEN
                    'LL:' || ROUND(COALESCE(c.lat, m.lat) / 0.5) * 0.5
                    || ':' || ROUND(COALESCE(c.lon, m.lon) / 0.5) * 0.5
                ELSE c.loose_colocator
            END AS loose_colocator
        FROM Charities c
        LEFT JOIN _charity_lat_map m ON c.charity_id = m.charity_id
        """)
        ccount = self.db_ops.execute_query("SELECT COUNT(*) FROM Charities_latfill").fetchone()[0]
        log_info(f"Charities_latfill rows={ccount:,} — swapping")
        self.db_ops.execute_query("DROP TABLE Charities")
        self.db_ops.execute_query("ALTER TABLE Charities_latfill RENAME TO Charities")
        self.db_ops.execute_query("DROP TABLE IF EXISTS _charity_zip_keys")
        self.db_ops.execute_query("DROP TABLE IF EXISTS _charity_lat_map")
        try:
            self.db_ops.execute_query("ALTER TABLE Charities ADD PRIMARY KEY (charity_id)")
        except Exception as e:
            log_info(f"Charities ADD PRIMARY KEY failed ({e}); UNIQUE INDEX fallback")
            self.db_ops.execute_query(
                "CREATE UNIQUE INDEX IF NOT EXISTS PRIMARY_Charities_0 ON Charities(charity_id)"
            )
        for ddl in (
            "CREATE UNIQUE INDEX IF NOT EXISTS Charities_xml_name_key ON Charities(xml_name)",
            "CREATE INDEX IF NOT EXISTS idx_charities_colocator ON Charities(colocator)",
            "CREATE INDEX IF NOT EXISTS idx_charities_denominator ON Charities(denominator)",
            "CREATE INDEX IF NOT EXISTS idx_charities_ein ON Charities(ein)",
            "CREATE INDEX IF NOT EXISTS idx_charities_form_type ON Charities(form_type)",
            "CREATE INDEX IF NOT EXISTS idx_charities_lat ON Charities(lat)",
            "CREATE INDEX IF NOT EXISTS idx_charities_lon ON Charities(lon)",
            "CREATE INDEX IF NOT EXISTS idx_charities_loose_colocator ON Charities(loose_colocator)",
            "CREATE INDEX IF NOT EXISTS idx_charities_org_type ON Charities(org_type)",
            "CREATE INDEX IF NOT EXISTS idx_charities_tax_year ON Charities(tax_year)",
        ):
            try:
                self.db_ops.execute_query(ddl)
            except Exception as e:
                log_info(f"Charities index recreate skipped: {ddl[:50]}… ({e})")

        try:
            self.db_ops.execute_query("CHECKPOINT")
        except Exception:
            pass

        log_info("lat/lon columns populated via equality-join CTAS + indexes created")
        print("[grant_match] lat/lon equality-join fill complete", flush=True)
    
    def _process_batch(self, batch: List[Dict[str, Any]]) -> PendingDatabaseContext:
        context = PendingDatabaseContext()
        updates = []

        for item in batch:
            name = item['grantee_name']
            loose_colocator = item.get('loose_colocator')
            best_ein = None
            source = None

            # 1. Geo fallback first
            if loose_colocator:
                best_ein = self._geo_fallback_match(item)
                if best_ein:
                    source = 'geo_fallback'

            # 2. Authoritative specific loose_colocator
            if not best_ein and loose_colocator:
                row = self.db_ops.execute_query(
                    "SELECT ein FROM AuthoritativeEin WHERE name = ? AND loose_colocator = ? LIMIT 1",
                    [name, loose_colocator]
                ).fetchone()
                if row:
                    best_ein = row[0]
                    source = 'authoritative-colocator'

            # 3. Hail mary: global name match
            if not best_ein:
                row = self.db_ops.execute_query(
                    "SELECT ein FROM AuthoritativeEin WHERE name = ? AND loose_colocator = 'NULL' LIMIT 1",
                    [name]
                ).fetchone()
                if row:
                    best_ein = row[0]
                    source = 'authoritative-global'

            # 4. Final fallback: GIN
            if not best_ein:
                best_ein = self._generate_gin(name)
                source = 'gin'

            final_ein = best_ein or '8686'
            updates.append({'grant_id': item['grant_id'], 'recipient_ein': final_ein})

            # Scoped propagation
            if final_ein and loose_colocator:
                prop_op = DatabaseOperation(
                    DatabaseOperationType.GENERIC_UPDATE,
                    data={
                        'table': 'Grants',
                        'set_clause': 'recipient_ein = ?',
                        'where_clause': "grantee_name = ? AND loose_colocator = ? AND (recipient_ein IS NULL OR recipient_ein = '8686')",
                        'params': [final_ein, name, loose_colocator]
                    }
                )
                context.addOperationToDatabase(prop_op)

                # Update AuthoritativeEin via proper operation (consumer will handle it)
                if False and source in ('geo_fallback', 'gin'): # intentionally disable for now  there might be other writes.
                    auth_op = DatabaseOperation(
                        DatabaseOperationType.AUTHORITATIVE_EIN_UPDATE,
                        data={
                            'name': name,
                            'loose_colocator': loose_colocator,
                            'ein': best_ein
                        }
                    )
                    context.addOperationToDatabase(auth_op)

        # Bulk update this batch
        if updates:
            bulk_op = DatabaseOperation(
                DatabaseOperationType.GENERIC_UPDATE,
                data={'table': 'Grants', 'updates': updates, 'id_column': 'grant_id'}
            )
            context.addOperationToDatabase(bulk_op)

        # Progress
        progress_op = DatabaseOperation(
            DatabaseOperationType.PROGRESS_UPDATE,
            data={"count": len(batch)}
        )
        context.addOperationToDatabase(progress_op)

        return context
    
    def _generate_gin(self, name: str) -> str:
        """Full SHA256 GIN (70 + 64 hex chars). Zero practical collision risk."""
        cleaned = name.upper().strip()
        cleaned = COMPANY_SUFFIX_REGEX.sub('', cleaned)
        hash_obj = hashlib.sha256(cleaned.encode('utf-8'))
        return "70" + hash_obj.hexdigest()

    def get_work_count(self, max_files: Optional[int] = None) -> int:
        # Must match _get_work_batch predicate (feeder only enqueues loose_colocator rows).
        query = (
            "SELECT COUNT(*) FROM Grants "
            "WHERE recipient_ein IS NULL AND loose_colocator IS NOT NULL"
        )
        result = self.db_ops.execute_query(query)
        total = result.fetchone()[0]
        if max_files:
            total = min(total, max_files)
        return total

    def get_progress_config(self, max_files: Optional[int] = None) -> Tuple[int, str, str]:
        total = self.get_work_count(max_files)
        return total, 'grants', 'Matching grants to charities'

    def _feed_thread(self, work_queue: queue.Queue, max_files: Optional[int], num_producers: int):
        last_id = None
        enqueued = 0
        while True:
            if self.exit_processing:
                break
            batch, new_last = self._get_work_batch(last_id)
            if not batch:
                break
            work_queue.put(WorkUnit.batch(batch))
            enqueued += len(batch)
            last_id = new_last
            if max_files and enqueued >= max_files:
                break
        for i in range(num_producers):
            work_queue.put(WorkUnit.sentinel(i))

    def _get_work_batch(self, last_id: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        query = """
        SELECT grant_id, grantee_name, colocator, loose_colocator, grantee_sndx
        FROM Grants
        WHERE recipient_ein IS NULL and loose_colocator IS NOT NULL
        """
        params: Tuple = (self.batch_size,)
        if last_id:
            query += " AND grant_id > ?"
            params = (last_id,) + params
        query += " ORDER BY grant_id LIMIT ?"
        rows = self.db_ops.execute_query(query, params).fetchall()
        batch = [dict(zip(['grant_id', 'grantee_name', 'loose_colocator', 'grantee_sndx'], row)) for row in rows]
        new_last = rows[-1][0] if rows else None
        return batch, new_last

    def _get_best_ein(self, charities: List[Tuple[str, str, float, str]], grantee_name: str, grantee_sndx: str) -> str:
        """Get best EIN by jaccard, prefer same sndx, tiebreak wealth"""
        matches = []
        for ein, filer_name, wealth, sndx in charities:
            jacc = word_jaccard(grantee_name, filer_name)
            sndx_match = (sndx == grantee_sndx) * 0.2  # Bonus for sndx match
            score = jacc + sndx_match
            if score >= self.jaccard_threshold:
                matches.append((score, ein, wealth))
        
        if matches:
            matches.sort(key=lambda x: (-x[0], -x[2]))
            return matches[0][1]
        else:
            best = max(charities, key=lambda x: x[2])
            return best[0]

    def _geo_fallback_match(self, item: Dict[str, Any]) -> Optional[str]:
        """Fast exact match on loose_colocator (0.5° grid) — uses the index perfectly."""
        loose = item.get('loose_colocator')
        if not loose:
            return None

        candidates = self.db_ops.execute_query("""
            SELECT c.ein, 
                   c.filer_name, 
                   (COALESCE(c.govt_amt, 0) + COALESCE(c.receipt_amt, 0)) AS wealth, 
                   c.sndx
            FROM Charities c
            WHERE c.loose_colocator = ?
        """, [loose]).fetchall()

        return self._get_best_ein(candidates, item['grantee_name'], item['grantee_sndx']) if candidates else None
    def _global_fallback_match(self, grantee_name: str) -> Optional[str]:
        """Original global name fallback with LIKE and wealth"""
        words = grantee_name.lower().split()[:2]
        like_pattern = '%' + '%'.join(words) + '%'
        query_global = """
        SELECT ein, filer_name, (COALESCE(govt_amt, 0) + COALESCE(receipt_amt, 0)) AS wealth, sndx
        FROM Charities
        WHERE LOWER(filer_name) LIKE ?
        ORDER BY wealth DESC
        LIMIT 50
        """
        global_charities = self.db_ops.execute_query(query_global, [like_pattern]).fetchall()
        
        if not global_charities:
            return None
        
        matches = []
        for ein, filer_name, wealth, sndx in global_charities:
            jacc = word_jaccard(grantee_name, filer_name)
            if jacc >= self.jaccard_threshold:
                matches.append((jacc, ein, wealth))
        
        if matches:
            matches.sort(key=lambda x: (-x[0], -x[2]))
            return matches[0][1]
        else:
            best = max(global_charities, key=lambda x: x[2])
            return best[0]

    def _parse_zip(self, colocator: str) -> Optional[str]:
        if colocator and colocator.startswith('PO:'):
            return colocator.split(':')[2]
        return None # No zip code available