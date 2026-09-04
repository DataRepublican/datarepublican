#!/usr/bin/env python3
"""
einless_processor.py - Phonebook (exact-core) resolution for no-EIN grantees.

Runs after the address deduplication step and before match (address_matcher).

Self-contained: exports the einless input TSV artifacts from DuckDB (see
docs/pipeline_overview.md), then runs phonebook cream + DAF resolution and
writes results to Grants.recipient_ein_backfilled (raw recipient_ein is untouched).

Exported files (written to output_dir, default 990tools root):
  - distinct_grantee_names.tsv
  - distinct_grantee_names_clean.tsv
  - pure_no_ein_by_dollars.tsv
  - pure_no_ein_high_value_{1M,10M,100M}.tsv
  - bmf_analysis.tsv
  - ein_name_variants.tsv
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bmf_fuzzy_candidate_matcher import (
    build_exact_core_phonebook,
    is_big_pharmaish,
    is_generic_grantee,
    is_plausible_org_name,
    load_bmf,
    resolve_donor_advised_fund_ein,
    resolve_phonebook_name,
    clean_name_for_matching,
)
from database_operations import DatabaseOperations
from logging_utils import log_info, log_warning


def _normalize_ein(ein: str) -> str:
    return (ein or "").replace("-", "").replace(" ", "").strip()


# Dollar thresholds for high-value pure-no-EIN slices (matches rebuild_einless inputs).
HIGH_VALUE_SLICES: Tuple[Tuple[str, int], ...] = (
    ("pure_no_ein_high_value_1M.tsv", 1_000_000),
    ("pure_no_ein_high_value_10M.tsv", 10_000_000),
    ("pure_no_ein_high_value_100M.tsv", 100_000_000),
)


class EinlessProcessor:
    """DB-integrated einless step: export TSV inputs, phonebook-resolve, backfill Grants."""

    def __init__(
        self,
        db_ops: DatabaseOperations,
        output_dir: str | Path = ".",
        batch_size: int = 5000,
    ):
        self.db_ops = db_ops
        self.output_dir = Path(output_dir).resolve()
        self.batch_size = batch_size

    def run(self) -> Dict[str, int]:
        """
        Export einless TSV inputs from DuckDB, resolve no-EIN grantee names via
        phonebook cream (+ DAF), set Grants.recipient_ein_backfilled.
        """
        log_info("=== Starting einless (export TSVs + phonebook resolution) ===")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        log_info(f"Einless TSV output dir: {self.output_dir}")

        self._ensure_backfill_column()

        export_stats = self.export_input_tsvs()

        bmf = self._load_bmf_records()
        variants = self._load_variant_records()
        log_info(f"BMF records: {len(bmf):,}; variant records: {len(variants):,}")

        sig_to_ein = build_exact_core_phonebook(bmf, variants or None)
        log_info(f"Phone book: {len(sig_to_ein):,} unique good sig-seqs")
        del variants

        names = self._unresolved_grantee_names()
        log_info(f"Distinct unresolved grantee names: {len(names):,}")

        resolutions: List[Tuple[str, str, str]] = []
        daf_count = cream_count = 0
        skipped_big = skipped_implausible = 0

        for i, name in enumerate(names):
            if i > 0 and i % 100000 == 0:
                log_info(
                    f"  {i:,}/{len(names):,} names scanned, {len(resolutions):,} resolved so far"
                )
            ein, source = self._resolve_name(name, sig_to_ein)
            if source == "daf":
                daf_count += 1
            elif source == "phonebook":
                cream_count += 1
            elif source == "skip_big_pharma":
                skipped_big += 1
                continue
            elif source == "skip_implausible":
                skipped_implausible += 1
                continue
            else:
                continue
            resolutions.append((name, _normalize_ein(ein), source))

        del sig_to_ein
        del bmf

        grants_updated = self._apply_resolutions(resolutions)

        stats = {
            **export_stats,
            "names_scanned": len(names),
            "resolved": len(resolutions),
            "daf": daf_count,
            "phonebook": cream_count,
            "skipped_big_pharma": skipped_big,
            "skipped_implausible": skipped_implausible,
            "grants_updated": grants_updated,
        }
        log_info(
            f"einless complete: {stats['resolved']:,} names resolved "
            f"(daf={daf_count:,}, phonebook={cream_count:,}), "
            f"{grants_updated:,} grant rows updated"
        )
        log_info("=== einless complete ===")
        return stats

    def export_input_tsvs(self) -> Dict[str, int]:
        """
        Export einless toolchain TSVs from Grants / IrsBmf / Charities via DuckDB COPY.
        SQL adapted from docs/pipeline_overview.md + pure-no-EIN logic in quitting.md.
        """
        log_info("Exporting einless input TSVs from DuckDB...")
        stats: Dict[str, int] = {}

        with self.db_ops.acquire_write_conn() as conn:
            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE einless_pure_no_ein AS
                SELECT
                    grantee_name,
                    COUNT(*)::BIGINT AS grant_count,
                    SUM(grant_amt)::DOUBLE AS dollars,
                    CAST(NULL AS VARCHAR) AS recipient_ein
                FROM Grants
                WHERE grantee_name IS NOT NULL AND TRIM(grantee_name) != ''
                GROUP BY grantee_name
                HAVING NOT BOOL_OR(
                    recipient_ein IS NOT NULL
                    AND TRIM(recipient_ein) != ''
                    AND recipient_ein != '8686'
                )
                """
            )

            exports: List[Tuple[str, str]] = [
                (
                    "distinct_grantee_names.tsv",
                    """
                    SELECT
                        grantee_name,
                        COUNT(*)::BIGINT AS grant_count,
                        SUM(grant_amt)::DOUBLE AS dollars,
                        recipient_ein
                    FROM Grants
                    WHERE grantee_name IS NOT NULL AND TRIM(grantee_name) != ''
                    GROUP BY grantee_name, recipient_ein
                    ORDER BY dollars DESC
                    """,
                ),
                (
                    "distinct_grantee_names_clean.tsv",
                    """
                    SELECT
                        grantee_name,
                        COUNT(*)::BIGINT AS grant_count,
                        SUM(grant_amt)::DOUBLE AS dollars
                    FROM Grants
                    WHERE grantee_name IS NOT NULL AND TRIM(grantee_name) != ''
                    GROUP BY grantee_name
                    ORDER BY dollars DESC
                    """,
                ),
                (
                    "pure_no_ein_by_dollars.tsv",
                    """
                    SELECT grantee_name, grant_count, dollars, recipient_ein
                    FROM einless_pure_no_ein
                    ORDER BY dollars DESC
                    """,
                ),
                (
                    "bmf_analysis.tsv",
                    """
                    SELECT DISTINCT
                        b.ein AS EIN,
                        b.name AS NAME,
                        COALESCE(addr.city, '') AS CITY,
                        COALESCE(addr.state, '') AS STATE,
                        b.asset_cd AS ASSET_CD
                    FROM IrsBmf b
                    LEFT JOIN (
                        SELECT
                            ein,
                            ANY_VALUE(city) AS city,
                            ANY_VALUE(state) AS state
                        FROM Addresses
                        WHERE address_type = 'bmf'
                          AND ein IS NOT NULL
                          AND TRIM(ein) != ''
                        GROUP BY ein
                    ) addr ON addr.ein = b.ein
                    WHERE b.ein IS NOT NULL
                      AND b.name IS NOT NULL
                      AND TRIM(b.name) != ''
                    ORDER BY b.ein
                    """,
                ),
                (
                    "ein_name_variants.tsv",
                    """
                    SELECT
                        c.ein,
                        c.filer_name AS name,
                        COUNT(g.grant_id)::BIGINT AS grant_count,
                        COALESCE(SUM(g.grant_amt), 0)::DOUBLE AS total_dollars
                    FROM Charities c
                    LEFT JOIN Grants g
                      ON REPLACE(REPLACE(COALESCE(g.recipient_ein, ''), '-', ''), ' ', '') = c.ein
                    WHERE c.ein IS NOT NULL AND TRIM(c.ein) != ''
                      AND c.filer_name IS NOT NULL AND TRIM(c.filer_name) != ''
                    GROUP BY c.ein, c.filer_name
                    ORDER BY total_dollars DESC
                    """,
                ),
            ]

            for filename, threshold in HIGH_VALUE_SLICES:
                exports.append(
                    (
                        filename,
                        f"""
                        SELECT grantee_name, grant_count, dollars, recipient_ein
                        FROM einless_pure_no_ein
                        WHERE dollars >= {threshold}
                        ORDER BY dollars DESC
                        """,
                    )
                )

            for filename, sql in exports:
                stats[filename] = self._copy_to_tsv(conn, filename, sql)

            conn.execute("DROP TABLE IF EXISTS einless_pure_no_ein")

        log_info(f"Exported {len(stats)} einless input TSVs to {self.output_dir}")
        return stats

    def _copy_to_tsv(self, conn, filename: str, sql: str) -> int:
        path = self.output_dir / filename
        count = conn.execute(f"SELECT COUNT(*) FROM ({sql}) sub").fetchone()[0]
        conn.execute(
            f"COPY ({sql}) TO '{path}' (HEADER, DELIMITER '\t')"
        )
        log_info(f"  {filename}: {count:,} rows → {path}")
        return count

    def _load_bmf_records(self) -> List[Dict]:
        path = self.output_dir / "bmf_analysis.tsv"
        if path.exists() and path.stat().st_size > 0:
            log_info(f"Loading BMF from exported {path}")
            return load_bmf(str(path))

        try:
            count_row = self.db_ops.execute_query(
                "SELECT COUNT(*) FROM IrsBmf WHERE ein IS NOT NULL AND name IS NOT NULL AND name != ''"
            ).fetchone()
            if count_row and count_row[0] > 0:
                log_info(f"Loading BMF names from IrsBmf table ({count_row[0]:,} rows)...")
                rows = self.db_ops.execute_query(
                    "SELECT ein, name, asset_cd FROM IrsBmf WHERE ein IS NOT NULL AND name IS NOT NULL AND name != ''"
                ).fetchall()
                return [{"ein": r[0], "name": r[1], "asset_cd": r[2]} for r in rows]
        except Exception as exc:
            log_warning(f"IrsBmf table unavailable ({exc})")

        raise FileNotFoundError(
            f"No BMF source: export {path} missing/empty and IrsBmf unavailable"
        )

    def _load_variant_records(self) -> List[Dict]:
        path = self.output_dir / "ein_name_variants.tsv"
        if path.exists() and path.stat().st_size > 0:
            log_info(f"Loading variants from exported {path}")
            return load_bmf(str(path))

        log_warning(f"{path} missing; phonebook will use BMF only")
        return []

    def _ensure_backfill_column(self) -> None:
        with self.db_ops.acquire_write_conn() as conn:
            conn.execute(
                "ALTER TABLE Grants ADD COLUMN IF NOT EXISTS recipient_ein_backfilled VARCHAR;"
            )

    def _unresolved_grantee_names(self) -> List[str]:
        rows = self.db_ops.execute_query(
            """
            SELECT DISTINCT grantee_name
            FROM Grants
            WHERE grantee_name IS NOT NULL
              AND TRIM(grantee_name) != ''
              AND (
                  recipient_ein_backfilled IS NULL
                  OR TRIM(recipient_ein_backfilled) = ''
              )
              AND (
                  recipient_ein IS NULL
                  OR TRIM(recipient_ein) = ''
                  OR recipient_ein = '8686'
              )
            ORDER BY grantee_name
            """
        ).fetchall()
        return [r[0] for r in rows]

    def _resolve_name(
        self, name: str, sig_to_ein: Dict[tuple, str]
    ) -> Tuple[Optional[str], str]:
        if is_generic_grantee(name):
            return None, "skip_implausible"
        cleaned = clean_name_for_matching(name)

        if is_big_pharmaish(cleaned):
            return None, "skip_big_pharma"

        if not is_plausible_org_name(cleaned or name):
            return None, "skip_implausible"

        daf_ein = resolve_donor_advised_fund_ein(name) or resolve_donor_advised_fund_ein(cleaned)
        if daf_ein:
            return daf_ein, "daf"

        ein = resolve_phonebook_name(name, sig_to_ein)
        if ein:
            return ein, "phonebook"

        return None, "unresolved"

    def _apply_resolutions(self, resolutions: List[Tuple[str, str, str]]) -> int:
        if not resolutions:
            log_info("No phonebook/DAF resolutions to apply")
            return 0

        total_grants = 0
        with self.db_ops.acquire_write_conn() as conn:
            conn.execute("DROP TABLE IF EXISTS einless_resolutions")
            conn.execute(
                """
                CREATE TEMP TABLE einless_resolutions (
                    grantee_name VARCHAR PRIMARY KEY,
                    resolved_ein VARCHAR NOT NULL,
                    source VARCHAR NOT NULL
                )
                """
            )

            for i in range(0, len(resolutions), self.batch_size):
                batch = resolutions[i : i + self.batch_size]
                conn.executemany(
                    "INSERT INTO einless_resolutions (grantee_name, resolved_ein, source) VALUES (?, ?, ?)",
                    batch,
                )

            unresolved_filter = """
                (
                    g.recipient_ein IS NULL
                    OR TRIM(g.recipient_ein) = ''
                    OR g.recipient_ein = '8686'
                )
                AND (
                    g.recipient_ein_backfilled IS NULL
                    OR TRIM(g.recipient_ein_backfilled) = ''
                )
            """

            before = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM Grants g
                INNER JOIN einless_resolutions r ON g.grantee_name = r.grantee_name
                WHERE {unresolved_filter}
                """
            ).fetchone()[0]

            conn.execute(
                f"""
                UPDATE Grants g
                SET recipient_ein_backfilled = r.resolved_ein
                FROM einless_resolutions r
                WHERE g.grantee_name = r.grantee_name
                  AND {unresolved_filter}
                """
            )

            conn.execute(
                """
                INSERT INTO Backfill (recipient_ein, name, source)
                SELECT DISTINCT r.resolved_ein, r.grantee_name, 'einless_' || r.source
                FROM einless_resolutions r
                ON CONFLICT (recipient_ein) DO NOTHING
                """
            )

            total_grants = before or 0
            conn.execute("DROP TABLE IF EXISTS einless_resolutions")

        return total_grants