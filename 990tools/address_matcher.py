#!/usr/bin/env python3
"""
address_matcher.py - Full grant normalization + recipient_ein backfill

Pipeline:
0. BMF pre-backfill (grantee_name_bmf + recipient_ein_backfilled for EIN'd grants)
1. Geo-aware name normalization (grantee_name_geo)
2. Full 6-step name + EIN consolidation (grantee_name_conc)
"""

import logging
import json
from pathlib import Path
from typing import Dict, Optional

from database_operations import DatabaseOperations
from logging_utils import log_info, log_error
import gzip
import os

# EINless integration note (post-hygiene "tie this off in a bow" per user review + architect plan):
# Use einless/ outputs (the cleaned_hard.tsv with new pass_through_flow flag, foreign_synthetic_ein,
# and _hard_flow.tsv / _hard_foreign.tsv splits from rebucket after the 2026-06 hygiene with 125404 hard)
# for early classification of subgrant/intermediary/foreign flows before full geo/name matching.
# This lets address_matcher respect "A passes to B" and grantor attribution instead of over-matching.
# See einless/ structure (option A), einless/code/einless_pipeline.py, and the architecture doc for details.
# Complements the ~89% phonebook cream; secondary geo pass on remaining einless hards is a natural next step.
# The einless learnings (flow patterns, statuses) also feed generate_name_rules canonical rollups.
class AddressMatcher:
    """Handles geo normalization + full name-based EIN backfill."""

    def __init__(self, db_ops: DatabaseOperations, rules_file: str = "name_rules.json"):
        self.db_ops = db_ops
        self.logger = logging.getLogger("address_matcher")
        self.rules_file = Path(rules_file)
        self.rules = None  # Lazy-loaded only when needed

    def _load_rules(self):
        """Load rules lazily (only when actually needed)."""
        if self.rules is not None:
            return self.rules  # Already loaded

        gz_path = 'name_rules.json.gz'
        json_path = 'name_rules.json'
        
        if os.path.exists(gz_path):
            path = gz_path
            print(f"Loading rules from {path}...")
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                self.rules = json.load(f)
        elif os.path.exists(json_path):
            path = json_path
            print(f"Loading rules from {path}...")
            with open(path, 'r', encoding='utf-8') as f:
                self.rules = json.load(f)
        else:
            print("Warning: name_rules.json.gz or name_rules.json not found!")
            self.rules = {}
        
        # Normalize format: some older runs produced a list instead of dict
        if isinstance(self.rules, list):
            print("Converting rules from list format to dict...")
            rules_dict = {}
            for item in self.rules:
                if isinstance(item, dict) and 'canonical' in item:
                    rules_dict[item['canonical']] = item.get('variants', [])
            self.rules = rules_dict
            print(f"Converted to {len(self.rules):,} rules")

        print(f"Loaded {len(self.rules):,} rules")
        return self.rules
    
    def dump_stats(self,conn, round:str):
        result=conn.execute("""SELECT 
            COUNT(*) AS total_grants,
            COUNT(CASE WHEN recipient_ein IS NOT NULL OR recipient_ein_backfilled IS NOT NULL THEN 1 END) AS grants_with_ein,
            ROUND(100.0 * COUNT(CASE WHEN recipient_ein IS NOT NULL OR recipient_ein_backfilled IS NOT NULL THEN 1 END) / COUNT(*), 2) AS pct_with_ein,
            COUNT(DISTINCT COALESCE(grantee_name_conc,grantee_name_geo,grantee_name_bmf, grantee_name)) AS distinct_names,
            COUNT(DISTINCT grantee_name) AS distinct_original_names,
            COUNT(DISTINCT grantee_name_bmf) AS distinct_bmf_names,
            COUNT(DISTINCT grantee_name_geo) AS distinct_geo_names,
            COUNT(DISTINCT grantee_name_conc) AS distinct_conc_names
            FROM Grants;
            """).fetchone()
        print(f"[{round}] Total grants: {result[0]:,}")
        print(f"[{round}] Grants with EIN: {result[1]:,}")
        print(f"[{round}] Percentage with EIN: {result[2]}%")
        print(f"[{round}] Distinct COALESCE names: {result[3]:,}")
        print(f"[{round}] Distinct original names: {result[4]:,}")
        print(f"[{round}] Distinct BMF names: {result[5]:,}")
        print(f"[{round}] Distinct geo names: {result[6]:,}")
        print(f"[{round}] Distinct canonical names: {result[7]:,}")

    
    def _chunked_address_ein_backfill(
        self, conn, *, dry_run: bool = False, batch_size: int = 50000
    ) -> int:
        """Backfill recipient_ein from name+canonical_address peers, one name-prefix at a time.

        The single-shot 26M ⨝ known-EIN join OOMs on 16GB hosts. Chunking by first letter of
        the match name keeps each join within memory; APPLY is a pure SQL UPDATE … FROM
        (no Python materialization of millions of rows).
        """
        log_info("Pass 1 (name+address): chunked grant_update_map by name prefix...")
        conn.execute("DROP TABLE IF EXISTS grant_update_map;")
        # Persistent temp-ish table so intermediate commits can survive; drop at end of step
        conn.execute(
            "CREATE OR REPLACE TABLE grant_update_map ("
            "grant_id UUID PRIMARY KEY, recipient_ein VARCHAR);"
        )

        prefixes = conn.execute(
            """
            SELECT DISTINCT LEFT(COALESCE(grantee_name_geo, grantee_name), 1) AS p
            FROM Grants
            WHERE (recipient_ein IS NULL OR recipient_ein = '')
            ORDER BY p NULLS FIRST
            """
        ).fetchall()
        log_info(f"  {len(prefixes)} name-prefix buckets for unmatched grants")

        total_map_rows = 0
        for n, (prefix,) in enumerate(prefixes, start=1):
            if prefix is None:
                g_pref = "LEFT(COALESCE(g.grantee_name_geo, g.grantee_name), 1) IS NULL"
                k_pref = "LEFT(COALESCE(g2.grantee_name_geo, g2.grantee_name), 1) IS NULL"
                label = "NULL"
            else:
                p = str(prefix).replace("'", "''")
                g_pref = f"LEFT(COALESCE(g.grantee_name_geo, g.grantee_name), 1) = '{p}'"
                k_pref = f"LEFT(COALESCE(g2.grantee_name_geo, g2.grantee_name), 1) = '{p}'"
                label = repr(prefix)

            before = conn.execute("SELECT COUNT(*) FROM grant_update_map").fetchone()[0] or 0
            conn.execute(
                f"""
                INSERT INTO grant_update_map (grant_id, recipient_ein)
                SELECT
                    g.grant_id,
                    ANY_VALUE(known.recipient_ein)
                FROM Grants g
                JOIN Addresses a
                    ON a.owner_id = g.grant_id
                   AND a.address_type = 'grant'
                JOIN (
                    SELECT
                        COALESCE(g2.grantee_name_geo, g2.grantee_name) AS match_name,
                        a2.canonical_address,
                        g2.recipient_ein
                    FROM Grants g2
                    JOIN Addresses a2
                        ON a2.owner_id = g2.grant_id
                       AND a2.address_type = 'grant'
                    WHERE g2.recipient_ein IS NOT NULL
                      AND g2.recipient_ein != ''
                      AND {k_pref}
                ) known
                    ON known.match_name = COALESCE(g.grantee_name_geo, g.grantee_name)
                   AND known.canonical_address = a.canonical_address
                WHERE (g.recipient_ein IS NULL OR g.recipient_ein = '')
                  AND {g_pref}
                  AND g.grant_id NOT IN (SELECT grant_id FROM grant_update_map)
                GROUP BY g.grant_id
                """
            )
            after = conn.execute("SELECT COUNT(*) FROM grant_update_map").fetchone()[0] or 0
            added = int(after) - int(before)
            total_map_rows = int(after)
            log_info(
                f"  prefix {label}: +{added:,} map rows "
                f"(bucket {n}/{len(prefixes)}, map total {total_map_rows:,})"
            )
            if n % 3 == 0:
                self.db_ops._intermediate_commit_and_checkpoint(conn, total_map_rows)

        if dry_run:
            log_info(f"Pass 1 dry-run: would update {total_map_rows:,} grants")
            conn.execute("DROP TABLE IF EXISTS grant_update_map;")
            return total_map_rows

        # Apply in SQL — avoid loading millions of rows into Python
        result = conn.execute(
            """
            UPDATE Grants g
            SET recipient_ein_backfilled = m.recipient_ein
            FROM grant_update_map m
            WHERE g.grant_id = m.grant_id
              AND (g.recipient_ein IS NULL OR g.recipient_ein = '')
              AND (g.recipient_ein_backfilled IS NULL OR g.recipient_ein_backfilled = '')
            """
        )
        # DuckDB returns update count as first column when available
        try:
            updated = int(result.fetchone()[0]) if result else total_map_rows
        except Exception:
            updated = total_map_rows
        log_info(f"Pass 1 (name+address) updated: {updated:,} grants (map size {total_map_rows:,})")
        self.db_ops._intermediate_commit_and_checkpoint(conn, updated)
        conn.execute("DROP TABLE IF EXISTS grant_update_map;")
        return updated

    def match_grants(self, dry_run: bool = False, batch_size: int = 50000) -> Dict[str, int]:
        """Full pipeline: BMF pre-backfill → geo normalization → name-based EIN consolidation."""
        self._load_rules()  # Lazy load rules only when we actually run matching
        log_info("Starting full grant normalization + EIN backfill...")

        stats = {
            "geo_normalized": 0,
            "name_normalized_updated": 0,
            "total_updated": 0
        }

        with self.db_ops.acquire_write_conn() as conn:
            conn.execute("BEGIN TRANSACTION")

            # Conservative defaults for 16GB hosts (override via DUCKDB_MEMORY_LIMIT)
            import os
            mem = os.environ.get("DUCKDB_MEMORY_LIMIT", "10GB")
            conn.execute(f"SET memory_limit = '{mem}'")
            conn.execute("SET threads = 2")
            conn.execute("SET preserve_insertion_order = false")

            try:
                # RULES:
                # recipient_ein_backfilled = backfilled EIN based on any method (BMF name match, address match, name match)
                # name flow: grantee_name (original) → grantee_name_bmf (BMF pre-backfill) → grantee_name_geo (geo normalization) → grantee_name_conc (full name-based consolidation)
                # grantee_name_bmf = official BMF name for grants that have (or match) an EIN in BMF table
                # final canonical name: COALESCE(grantee_name_conc, grantee_name_geo, grantee_name_bmf, grantee_name)

                # ====================== ALL COLUMNS FIRST ======================
                log_info("Creating all required columns...")
                conn.execute("ALTER TABLE Grants ADD COLUMN IF NOT EXISTS recipient_ein_backfilled VARCHAR;")
                conn.execute("ALTER TABLE Grants ADD COLUMN IF NOT EXISTS grantee_name_bmf VARCHAR;")
                conn.execute("ALTER TABLE Grants ADD COLUMN IF NOT EXISTS grantee_name_geo VARCHAR;")
                conn.execute("ALTER TABLE Grants ADD COLUMN IF NOT EXISTS grantee_name_conc VARCHAR;")

                # ====================== 0. BMF PRE-BACKFILL ======================
                log_info("Step 0: BMF pre-backfill - set official BMF name for all grants that have an EIN...")
                self.dump_stats(conn, "Start of BMF Pre-Backfill")

                # Simple and reliable: for every grant that already has recipient_ein,
                # look up the official name from IrsBmf and set grantee_name_bmf + recipient_ein_backfilled.
                # Normalize EINs (strip dashes/spaces) because source data sometimes has formatting differences.
                conn.execute("""
                    UPDATE Grants g
                    SET 
                        grantee_name_bmf = UPPER(b.name),
                        recipient_ein_backfilled = b.ein
                    FROM IrsBmf b
                    WHERE REPLACE(REPLACE(g.recipient_ein, '-', ''), ' ', '') = 
                          REPLACE(REPLACE(b.ein, '-', ''), ' ', '')
                      AND g.grantee_name_bmf IS NULL;
                """)

                self.db_ops._intermediate_commit_and_checkpoint(conn, 0)

                conn.execute("CREATE INDEX IF NOT EXISTS idx_grant_bmf_name ON Grants(grantee_name_bmf);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_grant_backfill_ein ON Grants(recipient_ein_backfilled);")

                self.dump_stats(conn, "After BMF Pre-Backfill")

                # ====================== 1. GEO NORMALIZATION ======================
                log_info("Step 1: Geo-aware name normalization...")

                null_geo = conn.execute(
                    "SELECT COUNT(*) FROM Grants WHERE grantee_name_geo IS NULL"
                ).fetchone()[0]
                if null_geo and int(null_geo) > 0:
                    conn.execute(
                        "UPDATE Grants SET grantee_name_geo = UPPER(COALESCE(grantee_name_bmf, grantee_name)) "
                        "WHERE grantee_name_geo IS NULL;"
                    )
                    self.dump_stats(conn, "After Case Normalization")

                    BATCH_SIZE = 1000
                    commit_threshold = 0

                    for core, rule in self.rules.items():
                        variants = rule.get('variants', []) if isinstance(rule, dict) else rule
                        if not variants:
                            continue

                        log_info(f"Processing rule '{core}' with {len(variants):,} variants...")

                        for i in range(0, len(variants), BATCH_SIZE):
                            batch = variants[i:i + BATCH_SIZE]
                            # Variants are already UPPER (rules generation lowercases then UPPERs)
                            variant_list = "', '".join(v.replace("'", "''") for v in batch)

                            # Pass 1: BMF names (fast path — grantee_name_bmf already UPPER from BMF step;
                            # NULLs naturally excluded by IN, no COALESCE needed)
                            conn.execute(f"""
                                UPDATE Grants
                                SET grantee_name_geo = '{core.replace("'", "''").upper()}'
                                WHERE grantee_name_geo IS NULL
                                  AND grantee_name_bmf IN ('{variant_list}')
                            """)

                            # Pass 2: Original names (grantee_name is mixed-case so UPPER() required here;
                            # automatically skips rows already set by Pass 1)
                            conn.execute(f"""
                                UPDATE Grants
                                SET grantee_name_geo = '{core.replace("'", "''").upper()}'
                                WHERE grantee_name_geo IS NULL
                                  AND UPPER(grantee_name) IN ('{variant_list}')
                            """)

                            commit_threshold += 1
                            if commit_threshold % 10 == 0:  # commit every 10 batches to avoid long transactions
                                self.db_ops._intermediate_commit_and_checkpoint(conn, 0)
                    self.db_ops._intermediate_commit_and_checkpoint(conn, stats["geo_normalized"])

                    self.dump_stats(conn, "After Geo Rules Normalization")
                    # Fallback (should be no-op now)
                    conn.execute("""
                        UPDATE Grants
                        SET grantee_name_geo = UPPER(grantee_name)
                        WHERE grantee_name_geo IS NULL
                    """)

                    # Small cleanups
                    conn.execute("UPDATE Grants SET grantee_name_geo = REGEXP_REPLACE(grantee_name_geo, ',\\s*$', '') WHERE grantee_name_geo IS NOT NULL")
                    conn.execute("UPDATE Grants SET grantee_name_geo = REGEXP_REPLACE(grantee_name_geo, 'B&GC', 'BOYS AND GIRLS CLUB', 'i') WHERE grantee_name_geo IS NOT NULL")
                    conn.execute("UPDATE Grants SET grantee_name_geo = REGEXP_REPLACE(grantee_name_geo, '\\bBSA\\b', 'BOY SCOUTS OF AMERICA', 'i') WHERE grantee_name_geo IS NOT NULL")
                    self.dump_stats(conn, "After Geo Normalization+Case")
                    self.db_ops._intermediate_commit_and_checkpoint(conn, stats["geo_normalized"])
                else:
                    log_info("Step 1: grantee_name_geo already fully populated — skipping geo rules")

                conn.execute("CREATE INDEX IF NOT EXISTS idx_grant_geo_name ON Grants(grantee_name_geo);")
                stats["geo_normalized"] = conn.execute("SELECT COUNT(*) FROM Grants WHERE grantee_name_geo IS NOT NULL").fetchone()[0]
                log_info(f"Geo normalization complete: {stats['geo_normalized']:,} rows")

                self.db_ops._intermediate_commit_and_checkpoint(conn, stats["geo_normalized"])

                # ====================== Address Backfill (chunked by name prefix) ======================
                # Full 26M ⨝ known-EIN grants OOM'd on 16GB hosts; process one first-letter bucket at a time.
                stats['address_match_updated'] = self._chunked_address_ein_backfill(
                    conn, dry_run=dry_run, batch_size=batch_size
                )
                self.dump_stats(conn, "After Address Match Backfill")

                # ====================== ADDRESS BACKFILL FROM BMF/CHARITY ======================
                log_info("Step 1.5: Address backfill from BMF/Charity (name + address match)...")
                address_backfilled = self.address_backfill(conn, max_items=None)  # process everything (no artificial limit)
                stats["address_backfilled"] = address_backfilled
                self.dump_stats(conn, "After BMF/Charity Address Backfill")

                # ====================== 2. FULL NAME + EIN CONSOLIDATION ======================
                log_info("Step 2: Full name-based EIN consolidation (memory-friendly batched version)...")

                # 2.0 - Create base_name_ein in small batches
                conn.execute("DROP TABLE IF EXISTS base_name_ein;")
                conn.execute("""
                    CREATE TABLE base_name_ein (
                        original_name VARCHAR,
                        recipient_ein VARCHAR,
                        grant_count BIGINT,
                        total_amount DECIMAL(18,2),
                        shortest_name VARCHAR,
                        grantee_name_conc VARCHAR
                    );
                """)

                einprefixes = conn.execute("""
                    SELECT DISTINCT LEFT(COALESCE(recipient_ein_backfilled, recipient_ein), 2) AS prefix
                    FROM Grants 
                    WHERE COALESCE(recipient_ein_backfilled, recipient_ein) IS NOT NULL
                    AND COALESCE(recipient_ein_backfilled, recipient_ein) != ''
                    ORDER BY prefix
                """).fetchall()

                commit_threshold =0 
                for (prefix,) in einprefixes:
                    log_info(f"Building base_name_ein for prefix {prefix}...")
                    conn.execute(f"""
                        INSERT INTO base_name_ein
                        SELECT
                            grantee_name_geo AS original_name,
                            COALESCE(recipient_ein_backfilled, recipient_ein) AS recipient_ein,
                            COUNT(*) AS grant_count,
                            SUM(grant_amt) AS total_amount,
                            NULL AS shortest_name,
                            NULL AS grantee_name_conc
                        FROM Grants
                        WHERE grantee_name_geo IS NOT NULL
                        AND LEFT(COALESCE(recipient_ein_backfilled, recipient_ein), 2) = '{prefix}'
                        GROUP BY grantee_name_geo, COALESCE(recipient_ein_backfilled, recipient_ein);
                    """)
                    commit_threshold += 1
                    if commit_threshold % 2 == 0:  # commit every 2 prefixes to keep memory low
                        self.db_ops._intermediate_commit_and_checkpoint(conn, 0)

                conn.execute("CREATE INDEX IF NOT EXISTS idx_base_ein ON base_name_ein(recipient_ein);")

                # 2.2 - Shortest name per EIN (batched)
                conn.execute("DROP TABLE IF EXISTS temp_per_ein;")
                conn.execute("CREATE TEMP TABLE temp_per_ein (recipient_ein VARCHAR, shortest_name VARCHAR);")
                commit_threshold = 0
                for (prefix,) in einprefixes:
                    log_info(f"Ranking shortest name for prefix {prefix}...")
                    conn.execute(f"""
                        INSERT INTO temp_per_ein
                        WITH ranked AS (
                            SELECT
                                b.recipient_ein,
                                b.original_name AS grantee_name,
                                ROW_NUMBER() OVER (
                                    PARTITION BY b.recipient_ein
                                    ORDER BY array_length(regexp_split_to_array(b.original_name, '\\s+'), 1) ASC,
                                            b.total_amount DESC
                                ) AS rn
                            FROM base_name_ein b
                            WHERE LEFT(b.recipient_ein, 2) = '{prefix}'
                        )
                        SELECT recipient_ein, grantee_name
                        FROM ranked
                        WHERE rn = 1;
                    """)
                    commit_threshold += 1
                    if commit_threshold % 2 == 0:  # commit every 2 prefixes to keep memory low
                        self.db_ops._intermediate_commit_and_checkpoint(conn, 0)

                # 2.3 - Push shortest_name back
                conn.execute("""
                    UPDATE base_name_ein b
                    SET shortest_name = t.shortest_name
                    FROM temp_per_ein t
                    WHERE b.recipient_ein = t.recipient_ein;
                """)

                # 2.4 - Apply prefix/suffix cleanup
                conn.execute("""
                    UPDATE base_name_ein
                    SET grantee_name_conc = CASE
                        WHEN shortest_name LIKE 'THE %' THEN regexp_replace(shortest_name, '^THE ', '', 'i')
                        WHEN shortest_name LIKE '% INC' THEN regexp_replace(shortest_name, ' INC$', '', 'i')
                        WHEN shortest_name LIKE '% FOUNDATION' THEN regexp_replace(shortest_name, ' FOUNDATION$', '', 'i')
                        WHEN shortest_name LIKE '% FOUNDATION INC' THEN regexp_replace(shortest_name, ' FOUNDATION INC$', '', 'i')
                        WHEN shortest_name LIKE '% LLC' THEN regexp_replace(shortest_name, ' LLC$', '', 'i')
                        WHEN shortest_name ~ ' (CORPORATION|CORP)$' THEN regexp_replace(shortest_name, ' (CORPORATION|CORP)$', '', 'i')
                        WHEN shortest_name ~ ' ASSOCIATION( INC)?$' THEN regexp_replace(shortest_name, ' ASSOCIATION( INC)?$', '', 'i')
                        WHEN shortest_name ~ ' (SCHOOL|SCHOOL DISTRICT)$' THEN regexp_replace(shortest_name, ' (SCHOOL|SCHOOL DISTRICT)$', '', 'i')
                        WHEN shortest_name ~ ' (CHURCH|METHODIST CHURCH|BAPTIST CHURCH)$' THEN regexp_replace(shortest_name, ' (CHURCH|METHODIST CHURCH|BAPTIST CHURCH)$', '', 'i')
                        WHEN shortest_name ~ ' CENTER( INC)?$' THEN regexp_replace(shortest_name, ' CENTER( INC)?$', '', 'i')
                        ELSE shortest_name
                    END;
                """)

                # 2.5 - Final mapping table (with DISTINCT ON to prevent duplicates)
                self.db_ops._intermediate_commit_and_checkpoint(conn, 0)
                conn.execute("DROP TABLE IF EXISTS name_mapping;")
                conn.execute("""
                    CREATE TABLE name_mapping AS
                    SELECT DISTINCT ON (grantee_name_conc)
                        grantee_name_conc AS match_name,
                        ANY_VALUE(recipient_ein ORDER BY total_amount DESC) AS winner_ein
                    FROM base_name_ein
                    GROUP BY grantee_name_conc;
                """)

                self.db_ops._intermediate_commit_and_checkpoint(conn, 0)
                log_info(f"name_mapping created with {conn.execute('SELECT COUNT(*) FROM name_mapping').fetchone()[0]:,} rows")

                # 2.6: Slow but bulletproof – one grant at a time
                log_info("Step 2.6: Slow but bulletproof backfill – one grant at a time...")

                # Build the list of grants that need updating
                conn.execute("DROP TABLE IF EXISTS grant_update_map;")
                conn.execute("""
                CREATE TABLE grant_update_map (
                    grant_id UUID PRIMARY KEY,
                    winner_ein VARCHAR,
                    new_conc_name VARCHAR
                );
                """)

                conn.execute("""
                INSERT INTO grant_update_map (grant_id, winner_ein, new_conc_name)
                SELECT DISTINCT ON (g.grant_id)
                    g.grant_id,
                    m.winner_ein,
                    m.match_name
                FROM Grants g
                JOIN name_mapping m
                  ON g.grantee_name_geo = m.match_name
                WHERE g.grantee_name_conc IS NULL
                ORDER BY g.grant_id;
                """)
                
                conn.execute("""
                DELETE FROM grant_update_map 
                WHERE grant_id IN (
                    '019d6408-f047-706e-9916-cd13c42ef0c4',
                    '019d6409-f1c6-79c7-e076-73c6bd48cabc',
                    '019d6408-eec3-76ff-577a-43e78a6b7354'
                );
                """);

                total_to_update = conn.execute("SELECT COUNT(*) FROM grant_update_map").fetchone()[0]
                log_info(f"Prepared {total_to_update:,} grants for backfill")

                updated_this_step = 0
                last_grant_id = None

                while True:
                    if last_grant_id is None:
                        row = conn.execute("""
                            SELECT grant_id, winner_ein, new_conc_name 
                            FROM grant_update_map 
                            ORDER BY grant_id 
                            LIMIT 1
                        """).fetchone()
                    else:
                        row = conn.execute("""
                            SELECT grant_id, winner_ein, new_conc_name 
                            FROM grant_update_map 
                            WHERE grant_id > ?
                            ORDER BY grant_id 
                            LIMIT 1
                        """, [last_grant_id]).fetchone()

                    if not row:
                        break
                    
                    grant_id, winner_ein, new_conc_name = row

                    conn.execute("""
                        UPDATE Grants 
                        SET 
                            recipient_ein_backfilled = ?,
                            grantee_name_conc = ?
                        WHERE grant_id = ?;
                    """, [winner_ein, new_conc_name, grant_id])

                    # Remove from map immediately so duplicates (if any) don't cause conflicts
                    conn.execute("DELETE FROM grant_update_map WHERE grant_id = ?", [grant_id])

                    updated_this_step += 1
                    last_grant_id = grant_id

                    if updated_this_step % 5000 == 0:
                        log_info(f"Updated {updated_this_step:,} / {total_to_update:,} grants so far...")
                        conn.commit()   # batch commit every 5000 rows

                    if updated_this_step % 100000 == 0:
                        conn.execute("CHECKPOINT")  # periodic checkpoint for long runs

                conn.commit()
                conn.execute("CHECKPOINT")
                log_info("Final checkpoint done")

                stats["name_normalized_updated"] = updated_this_step
                log_info(f"Name-based backfill complete. Updated {updated_this_step:,} grants")

                # Add address backfill count if it ran
                if "address_backfilled" not in stats:
                    stats["address_backfilled"] = 0

                return stats

            except Exception as e:
                conn.rollback()
                log_error(f"Full grant matching failed: {e}", exc_info=True)
                raise

    def address_backfill(self, conn, max_items: Optional[int] = None, dry_run: bool = False) -> int:
        """
        Backfill recipient_ein for grants using clean canonical addresses + canonical names.
        
        Only backfills when BOTH:
        1. The grant's canonical address matches a non-grant address (BMF or Charity) that has an EIN
        2. The grant's canonical name (grantee_name_geo or grantee_name_conc) matches the canonical name of the source
        
        This is much safer than pure address matching (which had 80.9% name mismatch).
        """
        log_info("Starting address-based EIN backfill from BMF/Charity...")

        # Create temp table for candidates
        conn.execute("DROP TABLE IF EXISTS address_backfill_candidates;")
        conn.execute("""
            CREATE TEMP TABLE address_backfill_candidates AS
                    WITH grant_grants AS (
                        SELECT 
                            g.grant_id,
                            COALESCE(g.grantee_name_conc, g.grantee_name_geo, g.grantee_name) AS canonical_name,
                            a.canonical_address
                        FROM Grants g
                        JOIN Addresses a 
                            ON a.owner_id = g.grant_id 
                           AND a.address_type = 'grant'
                        WHERE (g.recipient_ein IS NULL OR g.recipient_ein = '')
                          AND a.canonical_address IS NOT NULL
                          AND a.canonical_address != ''
                    ),
                    source_with_ein AS (
                        -- BMF sources
                        SELECT 
                            b.ein AS ein,
                            COALESCE(b.name, '') AS canonical_name,
                            a.canonical_address
                        FROM IrsBmf b
                        JOIN Addresses a 
                            ON a.owner_id = b.irsbmf_id 
                           AND a.address_type = 'bmf'
                        WHERE b.ein IS NOT NULL 
                          AND b.ein != ''
                          AND a.canonical_address IS NOT NULL
                          AND a.canonical_address != ''
                        
                        UNION ALL
                        
                        -- Charity sources
                        SELECT 
                            c.ein,
                            COALESCE(c.filer_name, '') AS canonical_name,
                            a.canonical_address
                        FROM Charities c
                        JOIN Addresses a 
                            ON a.owner_id = c.charity_id 
                           AND a.address_type = 'charity'
                        WHERE c.ein IS NOT NULL 
                          AND c.ein != ''
                          AND a.canonical_address IS NOT NULL
                          AND a.canonical_address != ''
                    )
                    SELECT DISTINCT
                        gg.grant_id,
                        s.ein AS winner_ein,
                        s.canonical_name AS source_name
                    FROM grant_grants gg
                    JOIN source_with_ein s
                      ON s.canonical_address = gg.canonical_address
                     AND s.canonical_name = gg.canonical_name
                    LIMIT ?;
                """, [max_items or 999999999])

        total_candidates = conn.execute("SELECT COUNT(*) FROM address_backfill_candidates").fetchone()[0]
        log_info(f"Found {total_candidates:,} grants that can be backfilled via address + name match")

        if total_candidates == 0:
            return 0

        # Update in batches
        updated = 0
        last_grant_id = None
        batch_size = 5000

        while True:
            if last_grant_id is None:
                rows = conn.execute("""
                    SELECT grant_id, winner_ein 
                    FROM address_backfill_candidates 
                    ORDER BY grant_id 
                    LIMIT ?
                """, [batch_size]).fetchall()
            else:
                rows = conn.execute("""
                    SELECT grant_id, winner_ein 
                    FROM address_backfill_candidates 
                    WHERE grant_id > ?
                    ORDER BY grant_id 
                    LIMIT ?
                """, [last_grant_id, batch_size]).fetchall()

            if not rows:
                break

            for grant_id, winner_ein in rows:
                if dry_run:
                    log_info(f"DRY RUN: Would set recipient_ein_backfilled = {winner_ein} for grant {grant_id}")
                else:
                    conn.execute("""
                        UPDATE Grants 
                        SET recipient_ein_backfilled = ?
                        WHERE grant_id = ?
                    """, [winner_ein, grant_id])

                updated += 1
                last_grant_id = grant_id

            conn.commit()
            log_info(f"Updated {updated:,} / {total_candidates:,} grants so far...")

        conn.execute("CHECKPOINT")
        log_info(f"Address backfill complete. Updated {updated:,} grants")
        return updated