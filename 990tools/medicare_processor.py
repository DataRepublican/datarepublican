#!/usr/bin/env python3
"""
medicare_processor.py - CMS NPPES + Medicaid provider spending ingest.

Downloads (curl, idempotent), raw DuckDB import, then promotes to production
tables with addresses split into Addresses (owner_id + address_type).

Data sources:
  - NPPES dissemination zip (CMS NPI_Files.html → download.cms.gov/nppes)
  - Medicaid provider spending Parquet (T-MSIS public use from opendata.hhs.gov;
    optional MEDICARE_SPENDING_URL override, legacy CSV fallback)
  - HCPCS + NOC code reference files
  - NPPES taxonomy (pl_pfile) → supplemental lookup
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, Optional

from database_operations import DatabaseOperations
from download_utils import (
    MEDICAID_SPENDING_DATASET_PAGE,
    NPPES_FILES_PAGE,
    discover_medicaid_spending_download_url,
    discover_nppes_zip_url,
    ensure_download,
)
from logging_utils import log_info, log_warning
from models import Address, MedicareProvider

NPPES_BATCH_SIZE = 15_000
NPPES_CHECKPOINT_EVERY = 10
SPENDING_NPI_PREFIX_BATCHES = 100


LEGACY_DATA_DIR = Path("/Volumes/Data/medicaid")
DEFAULT_SPENDING_FILENAME = "medicaid-provider-spending.parquet"
DEFAULT_SPENDING_ZIP_FILENAME = "medicaid-provider-spending.csv.zip"
LEGACY_SPENDING_CSV = "medicaid-provider-spending.csv"
NPPES_ZIP_GLOB = "NPPES_Data_Dissemination_*.zip"


class MedicareProcessor:
    def __init__(self, db_ops: DatabaseOperations, data_dir: str | Path):
        self.db_ops = db_ops
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.spending_url = os.environ.get("MEDICARE_SPENDING_URL", "").strip()

    def run(self) -> Dict[str, int]:
        log_info("=== Starting Medicare step (download → raw ingest → promote) ===")
        stats = {
            "downloads": 0,
            "hcpcs_codes": 0,
            "noc_codes": 0,
            "nppes_providers": 0,
            "spending_rows": 0,
        }

        stats["downloads"] += int(self._ensure_lookups())
        nppes_csv = self._ensure_nppes_csv(stats)
        if nppes_csv:
            stats["nppes_providers"] = self._ingest_nppes(nppes_csv)

        spending_file = self._ensure_spending_file(stats)
        if spending_file:
            stats["spending_rows"] = self._ingest_spending(spending_file)

        log_info(f"=== Medicare complete: {stats} ===")
        return stats

    def _ensure_lookups(self) -> bool:
        downloaded = False
        downloaded |= self._ensure_hcpcs_codes()
        downloaded |= self._ensure_noc_codes()
        downloaded |= self._ensure_nppes_code_values()
        return downloaded

    def _ensure_hcpcs_codes(self) -> bool:
        """Prefer CMS Level II + PFS RVU loader; fall back to legacy TSV."""
        # New path: load_hcpcs_from_cms.py (Level II quarterly + PFS RVU short labels)
        try:
            from load_hcpcs_from_cms import main as load_hcpcs_main

            log_info("Loading hcpcs_codes from CMS Level II + PFS RVU…")
            old = sys.argv[:]
            try:
                sys.argv = [
                    "load_hcpcs_from_cms",
                    "--db-path",
                    str(self.db_ops.db_path),
                    "--cache-dir",
                    str(self.data_dir / "hcpcs_cms"),
                ]
                rc = load_hcpcs_main()
            finally:
                sys.argv = old
            if rc == 0:
                return True
            log_warning(f"CMS HCPCS loader rc={rc}; trying legacy TSV")
        except Exception as e:
            log_warning(f"CMS HCPCS loader failed ({e}); trying legacy TSV")

        dest = self.data_dir / "HCPC_CODES.tsv"
        legacy = LEGACY_DATA_DIR / "HCPC_CODES.tsv"
        if not dest.exists() and legacy.exists():
            log_info(f"Copying HCPCS reference from {legacy}")
            shutil.copy2(legacy, dest)

        if not dest.exists():
            log_warning("HCPCS reference file missing; skipping hcpcs_codes load")
            return False

        with self.db_ops.acquire_write_conn() as conn:
            conn.execute("DELETE FROM hcpcs_codes")
            conn.execute(
                f"""
                INSERT INTO hcpcs_codes (code, description, long_description)
                SELECT
                    TRIM(HCPC),
                    NULLIF(TRIM("SHORT DESCRIPTION"), ''),
                    NULLIF(TRIM("LONG DESCRIPTION"), '')
                FROM read_csv('{dest}', delim='\\t', header=true, auto_detect=true)
                WHERE TRIM(HCPC) != ''
                """
            )
            count = conn.execute("SELECT COUNT(*) FROM hcpcs_codes").fetchone()[0]
            log_info(f"  hcpcs_codes: {count:,} rows")
        return False

    def _ensure_noc_codes(self) -> bool:
        """Load NOC codes from TSV if present (export from CMS NOC xlsx)."""
        for candidate in (
            self.data_dir / "noc_codes.tsv",
            LEGACY_DATA_DIR / "noc_codes.tsv",
        ):
            if candidate.exists():
                with self.db_ops.acquire_write_conn() as conn:
                    conn.execute("DELETE FROM noc_codes")
                    conn.execute(
                        f"""
                        INSERT INTO noc_codes (code, description)
                        SELECT column0, column1
                        FROM read_csv('{candidate}', delim='\\t', header=true, auto_detect=true)
                        """
                    )
                    count = conn.execute("SELECT COUNT(*) FROM noc_codes").fetchone()[0]
                    log_info(f"  noc_codes: {count:,} rows from {candidate.name}")
                return False

        xlsx = LEGACY_DATA_DIR / "NOC codes_JAN2026.xlsx"
        if xlsx.exists():
            log_warning(
                f"NOC xlsx at {xlsx} — export to noc_codes.tsv (code\\tdescription) to load"
            )
        return False

    def _ensure_nppes_code_values(self) -> bool:
        """NUCC taxonomy CSV + core NPPES field code seeds → nppes_code_values."""
        downloaded = False
        taxonomy_url = os.environ.get(
            "NUCC_TAXONOMY_URL",
            "https://nucc.org/images/stories/CSV/nucc_taxonomy_251.csv",
        )
        taxonomy_dest = self.data_dir / "nucc_taxonomy.csv"
        try:
            if ensure_download(taxonomy_url, taxonomy_dest):
                downloaded = True
        except RuntimeError as exc:
            log_warning(f"NUCC taxonomy download failed: {exc}")

        with self.db_ops.acquire_write_conn() as conn:
            conn.execute("DELETE FROM nppes_code_values")

            conn.execute(
                """
                INSERT INTO nppes_code_values (field_name, code, description) VALUES
                ('Entity Type Code', '1', 'Individual'),
                ('Entity Type Code', '2', 'Organization')
                """
            )

            if taxonomy_dest.exists():
                conn.execute(
                    f"""
                    INSERT INTO nppes_code_values (field_name, code, description)
                    SELECT
                        'Healthcare Provider Taxonomy Code',
                        TRIM(Code),
                        TRIM(COALESCE("Display Name", Classification, Grouping))
                    FROM read_csv('{taxonomy_dest}', header=true, auto_detect=true)
                    WHERE TRIM(Code) != ''
                    ON CONFLICT (field_name, code) DO NOTHING
                    """
                )

            pdf = LEGACY_DATA_DIR / "NPPES_Data_Dissemination_CodeValues.pdf"
            if pdf.exists():
                log_info(
                    f"NPPES field code reference PDF at {pdf} — extend nppes_code_values from CSV export if needed"
                )

            count = conn.execute("SELECT COUNT(*) FROM nppes_code_values").fetchone()[0]
            log_info(f"  nppes_code_values: {count:,} rows")
        return downloaded

    def _ensure_nppes_csv(self, stats: Dict[str, int]) -> Optional[Path]:
        zip_path = self._latest_nppes_zip()
        if zip_path is None:
            url = discover_nppes_zip_url(NPPES_FILES_PAGE)
            if not url:
                log_warning(f"Could not discover NPPES zip URL from {NPPES_FILES_PAGE}")
                return self._find_npidata_csv()
            log_info(f"Discovered NPPES download: {url}")
            zip_path = self.data_dir / Path(url).name
            if ensure_download(url, zip_path):
                stats["downloads"] += 1

        if zip_path and zip_path.exists():
            return self._extract_npidata(zip_path)
        return self._find_npidata_csv()

    def _latest_nppes_zip(self) -> Optional[Path]:
        zips = sorted(self.data_dir.glob("NPPES_Data_Dissemination_*.zip"))
        if zips:
            return zips[-1]
        legacy = sorted(LEGACY_DATA_DIR.glob("NPPES_Data_Dissemination_*.zip"))
        return legacy[-1] if legacy else None

    def _extract_npidata(self, zip_path: Path) -> Optional[Path]:
        proc = subprocess.run(
            ["unzip", "-l", str(zip_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        npi_name = None
        for line in proc.stdout.splitlines():
            if "npidata_pfile" in line and line.endswith(".csv"):
                npi_name = line.split()[-1]
                break
        if not npi_name:
            return self._find_npidata_csv()

        dest = self.data_dir / Path(npi_name).name
        gz_dest = Path(str(dest) + ".gz")
        # Prefer existing plain or gzipped extract over re-unzip.
        if dest.exists():
            return dest
        if gz_dest.exists():
            return gz_dest

        log_info(f"Extracting {npi_name} from {zip_path.name}")
        subprocess.run(
            ["unzip", "-o", "-qq", str(zip_path), npi_name, "-d", str(self.data_dir)],
            check=True,
        )
        return dest if dest.exists() else None

    def _find_npidata_csv(self) -> Optional[Path]:
        """Locate npidata CSV; accept plain .csv or .csv.gz (newest mtime wins)."""
        candidates: list[Path] = []
        for d in (self.data_dir, LEGACY_DATA_DIR):
            if not d.exists():
                continue
            candidates.extend(d.glob("npidata_pfile_*.csv.gz"))
            candidates.extend(d.glob("npidata_pfile_*.csv"))
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    @staticmethod
    def _open_nppes_csv(csv_path: Path):
        """Open NPPES CSV as text; transparent gzip for *.csv.gz."""
        name = csv_path.name.lower()
        if name.endswith(".gz") or csv_path.suffix == ".gz":
            import gzip

            return gzip.open(
                csv_path, mode="rt", encoding="utf-8", errors="replace", newline=""
            )
        return open(csv_path, newline="", encoding="utf-8", errors="replace")

    @staticmethod
    def _trim(value) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _parse_nppes_date(value) -> Optional[str]:
        text = str(value).strip() if value is not None else ""
        if not text:
            return None
        if "/" in text:
            parts = [p.strip() for p in text.split("/")]
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                mm, dd, yyyy = parts
                return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
        return text

    def _existing_nppes_rows(self, conn) -> int:
        row = conn.execute("SELECT COUNT(*) FROM medicare_providers").fetchone()
        return int(row[0]) if row else 0

    def _promote_nppes_row(self, row: dict) -> tuple[Optional[MedicareProvider], list[Address]]:
        npi = self._trim(row.get("NPI"))
        if not npi:
            return None, []

        provider = MedicareProvider(
            npi=npi,
            entity_type_code=self._trim(row.get("Entity Type Code")),
            ein=self._trim(row.get("Employer Identification Number (EIN)")),
            organization_name=self._trim(
                row.get("Provider Organization Name (Legal Business Name)")
            ),
            provider_last_name=self._trim(row.get("Provider Last Name (Legal Name)")),
            provider_first_name=self._trim(row.get("Provider First Name")),
            provider_middle_name=self._trim(row.get("Provider Middle Name")),
            provider_credential=self._trim(row.get("Provider Credential Text")),
            enumeration_date=self._parse_nppes_date(row.get("Provider Enumeration Date")),
            last_update_date=self._parse_nppes_date(row.get("Last Update Date")),
            is_sole_proprietor=self._trim(row.get("Is Sole Proprietor")),
        )
        provider.prep_for_insert()

        addresses: list[Address] = []
        practice_line1 = self._trim(
            row.get("Provider First Line Business Practice Location Address")
        )
        if practice_line1:
            addresses.append(
                provider.build_address(
                    address_line1=practice_line1,
                    address_line2=self._trim(
                        row.get("Provider Second Line Business Practice Location Address")
                    ),
                    city=self._trim(
                        row.get("Provider Business Practice Location Address City Name")
                    ),
                    state=self._trim(
                        row.get("Provider Business Practice Location Address State Name")
                    ),
                    zip_code=self._trim(
                        row.get("Provider Business Practice Location Address Postal Code")
                    ),
                    address_type="nppes_practice",
                )
            )

        mailing_line1 = self._trim(row.get("Provider First Line Business Mailing Address"))
        if mailing_line1 and mailing_line1 != practice_line1:
            addresses.append(
                provider.build_address(
                    address_line1=mailing_line1,
                    address_line2=self._trim(
                        row.get("Provider Second Line Business Mailing Address")
                    ),
                    city=self._trim(
                        row.get("Provider Business Mailing Address City Name")
                    ),
                    state=self._trim(
                        row.get("Provider Business Mailing Address State Name")
                    ),
                    zip_code=self._trim(
                        row.get("Provider Business Mailing Address Postal Code")
                    ),
                    address_type="nppes_mailing",
                )
            )

        return provider, addresses

    def _promote_nppes_streaming(self, csv_path: Path, conn) -> int:
        total = 0
        existing = self._existing_nppes_rows(conn)
        skip_rows = existing
        skipped = 0
        batches = 0
        providers: list[MedicareProvider] = []
        addresses: list[Address] = []

        if existing:
            log_info(f"  medicare_providers: resuming — skip {skip_rows:,} CSV rows")
            print(f"  medicare_providers: resuming — skip {skip_rows:,} CSV rows", flush=True)
        else:
            conn.execute("DELETE FROM medicare_providers")
            conn.execute(
                """
                DELETE FROM Addresses
                WHERE address_type IN ('nppes_practice', 'nppes_mailing')
                """
            )

        with self._open_nppes_csv(csv_path) as fh:
            for row in csv.DictReader(fh):
                if not self._trim(row.get("NPI")):
                    continue
                if skipped < skip_rows:
                    skipped += 1
                    continue

                provider, row_addresses = self._promote_nppes_row(row)
                if provider is None:
                    continue
                providers.append(provider)
                addresses.extend(row_addresses)
                if len(providers) < NPPES_BATCH_SIZE:
                    continue

                self.db_ops.bulk_insert(providers, conn=conn, commit_batches=True)
                if addresses:
                    self.db_ops.bulk_insert(addresses, conn=conn, commit_batches=True)
                total += len(providers)
                batches += 1
                if batches % NPPES_CHECKPOINT_EVERY == 0:
                    conn.execute("CHECKPOINT")
                if batches % 20 == 0:
                    msg = (
                        f"  medicare_providers: +{total:,} this run "
                        f"({existing + total:,} total)"
                    )
                    log_info(msg)
                    print(msg, flush=True)
                providers = []
                addresses = []

        if providers:
            self.db_ops.bulk_insert(providers, conn=conn, commit_batches=True)
            if addresses:
                self.db_ops.bulk_insert(addresses, conn=conn, commit_batches=True)
            total += len(providers)
            conn.execute("CHECKPOINT")

        promoted = existing + total
        log_info(f"  medicare_providers: {promoted:,} rows")
        print(f"  medicare_providers: {promoted:,} rows", flush=True)
        return promoted

    def _ingest_nppes(self, csv_path: Path) -> int:
        marker = self.data_dir / ".nppes_ingest.json"
        if self._ingest_current("medicare_providers", csv_path, marker):
            return self.db_ops.execute_query(
                "SELECT COUNT(*) FROM medicare_providers"
            ).fetchone()[0]

        log_info(f"Ingesting NPPES from {csv_path} (streaming)")
        print(f"Ingesting NPPES from {csv_path} (streaming)", flush=True)
        with self.db_ops.acquire_write_conn() as conn:
            conn.execute("SET preserve_insertion_order=false")
            conn.execute("SET threads=2")
            conn.execute("SET memory_limit='8GB'")
            count = self._promote_nppes_streaming(csv_path, conn)
            self._save_ingest_marker(marker, csv_path)
            return count

    def _extract_spending_zip(self, zip_path: Path, csv_path: Path) -> None:
        if not zip_path.exists():
            return
        if (
            csv_path.exists()
            and csv_path.stat().st_mtime >= zip_path.stat().st_mtime
            and csv_path.stat().st_size > 0
        ):
            log_info(f"Spending CSV up to date: {csv_path.name}")
            return

        log_info(f"Extracting {zip_path.name} → {csv_path.name}")
        with zipfile.ZipFile(zip_path) as archive:
            members = [name for name in archive.namelist() if name.endswith(".csv")]
            if not members:
                raise RuntimeError(f"No CSV found inside {zip_path}")
            member = next(
                (name for name in members if "medicaid-provider-spending" in name),
                members[0],
            )
            with archive.open(member) as src, csv_path.open("wb") as dest:
                shutil.copyfileobj(src, dest)

    def _resolve_spending_download_url(self) -> Optional[str]:
        if self.spending_url:
            return self.spending_url

        url = discover_medicaid_spending_download_url(MEDICAID_SPENDING_DATASET_PAGE)
        if url:
            log_info(f"Discovered Medicaid spending download: {url}")
        else:
            log_warning(
                f"Could not discover Medicaid spending URL from {MEDICAID_SPENDING_DATASET_PAGE}"
            )
        return url

    def _spending_dest_for_url(self, url: str) -> Path:
        suffix = Path(url.split("?", 1)[0]).suffix.lower()
        if suffix == ".zip":
            return self.data_dir / DEFAULT_SPENDING_ZIP_FILENAME
        if suffix:
            return self.data_dir / f"medicaid-provider-spending{suffix}"
        return self.data_dir / DEFAULT_SPENDING_FILENAME

    def _ensure_spending_file(self, stats: Dict[str, int]) -> Optional[Path]:
        dest = self.data_dir / DEFAULT_SPENDING_FILENAME
        download_url = self._resolve_spending_download_url()

        if download_url:
            try:
                target = self._spending_dest_for_url(download_url)
                if download_url.endswith(".zip"):
                    if ensure_download(download_url, target):
                        stats["downloads"] += 1
                    csv_dest = self.data_dir / LEGACY_SPENDING_CSV
                    self._extract_spending_zip(target, csv_dest)
                    return csv_dest if csv_dest.exists() else None
                if ensure_download(download_url, target):
                    stats["downloads"] += 1
                dest = target
            except RuntimeError as exc:
                log_warning(f"Medicaid spending download failed: {exc}")

        if dest.exists():
            return dest

        for candidate in (
            self.data_dir / LEGACY_SPENDING_CSV,
            LEGACY_DATA_DIR / LEGACY_SPENDING_CSV,
            LEGACY_DATA_DIR / DEFAULT_SPENDING_FILENAME,
        ):
            if candidate.exists():
                log_info(f"Using legacy spending file at {candidate}")
                return candidate

        log_warning(
            "No medicaid provider spending file — download from "
            f"{MEDICAID_SPENDING_DATASET_PAGE} failed; set MEDICARE_SPENDING_URL "
            "or place parquet/csv in data dir"
        )
        return None

    def _ensure_spending_schema(self, conn) -> None:
        conn.execute(
            """
            ALTER TABLE medicare_provider_spending
            ADD COLUMN IF NOT EXISTS billing_provider_name VARCHAR
            """
        )
        conn.execute(
            """
            ALTER TABLE medicare_provider_spending
            ADD COLUMN IF NOT EXISTS servicing_provider_name VARCHAR
            """
        )

    @staticmethod
    def _spending_column_sql(conn, columns: set[str], *candidates: str, cast: str = "BIGINT") -> str:
        for name in candidates:
            if name in columns:
                return f"TRY_CAST(r.{name} AS {cast})"
        return "NULL"

    def _load_raw_spending(self, conn, source_path: Path) -> None:
        conn.execute("DROP TABLE IF EXISTS medicare_raw_spending")
        if source_path.suffix.lower() == ".parquet":
            conn.execute(
                f"""
                CREATE TABLE medicare_raw_spending AS
                SELECT * FROM read_parquet('{source_path}')
                """
            )
        else:
            conn.execute(
                f"""
                CREATE TABLE medicare_raw_spending AS
                SELECT * FROM read_csv('{source_path}', header=true, auto_detect=true, parallel=true)
                """
            )

    def _spending_source_sql(self, conn, source_path: Path) -> tuple[str, set[str]]:
        if source_path.suffix.lower() == ".parquet":
            path = str(source_path).replace("'", "''")
            source = f"read_parquet('{path}')"
            raw_columns = {
                row[0]
                for row in conn.execute(f"DESCRIBE SELECT * FROM {source} LIMIT 0").fetchall()
            }
            return source, raw_columns

        self._load_raw_spending(conn, source_path)
        raw_columns = {
            row[0] for row in conn.execute("DESCRIBE medicare_raw_spending").fetchall()
        }
        return "medicare_raw_spending", raw_columns

    def _insert_spending_batch(
        self,
        conn,
        source_sql: str,
        prefix: str,
        billing_name_sql: str,
        servicing_name_sql: str,
        beneficiaries_sql: str,
        claims_sql: str,
        paid_sql: str,
    ) -> None:
        conn.execute(
            f"""
            INSERT INTO medicare_provider_spending (
                id, billing_provider_npi, billing_provider_name,
                servicing_provider_npi, servicing_provider_name,
                hcpcs_code, claim_from_month,
                total_unique_beneficiaries, total_claims, total_paid
            )
            SELECT
                uuidv7(),
                r.BILLING_PROVIDER_NPI_NUM,
                {billing_name_sql},
                r.SERVICING_PROVIDER_NPI_NUM,
                {servicing_name_sql},
                r.HCPCS_CODE,
                r.CLAIM_FROM_MONTH,
                {beneficiaries_sql},
                {claims_sql},
                {paid_sql}
            FROM {source_sql} r
            LEFT JOIN medicare_providers billing
              ON billing.npi = r.BILLING_PROVIDER_NPI_NUM
            LEFT JOIN medicare_providers servicing
              ON servicing.npi = r.SERVICING_PROVIDER_NPI_NUM
            WHERE r.BILLING_PROVIDER_NPI_NUM IS NOT NULL
              AND TRIM(r.BILLING_PROVIDER_NPI_NUM) != ''
              AND SUBSTR(r.BILLING_PROVIDER_NPI_NUM, 1, 2) = ?
            """,
            (prefix,),
        )

    def _ingest_spending(self, source_path: Path) -> int:
        marker = self.data_dir / ".spending_ingest.json"
        if self._ingest_current("medicare_provider_spending", source_path, marker):
            return self.db_ops.execute_query(
                "SELECT COUNT(*) FROM medicare_provider_spending"
            ).fetchone()[0]

        provider_count = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM medicare_providers"
        ).fetchone()[0]
        if provider_count == 0:
            log_warning(
                "medicare_providers is empty — spending rows will have null provider names; "
                "run NPPES ingest first"
            )

        billing_name_sql = MedicareProvider.display_name_sql("billing")
        servicing_name_sql = MedicareProvider.display_name_sql("servicing")

        log_info(f"Ingesting Medicaid provider spending from {source_path} (batched)")
        print(f"Ingesting Medicaid provider spending from {source_path} (batched)", flush=True)
        with self.db_ops.acquire_write_conn() as conn:
            conn.execute("SET preserve_insertion_order=false")
            conn.execute("SET threads=2")
            conn.execute("SET memory_limit='8GB'")
            self._ensure_spending_schema(conn)
            source_sql, raw_columns = self._spending_source_sql(conn, source_path)
            beneficiaries_sql = self._spending_column_sql(
                conn,
                raw_columns,
                "TOTAL_PATIENTS",
                "TOTAL_UNIQUE_BENEFICIARIES",
            )
            claims_sql = self._spending_column_sql(
                conn,
                raw_columns,
                "TOTAL_CLAIM_LINES",
                "TOTAL_CLAIMS",
            )
            paid_sql = self._spending_column_sql(
                conn, raw_columns, "TOTAL_PAID", cast="DOUBLE"
            )

            conn.execute("DELETE FROM medicare_provider_spending")
            for batch in range(SPENDING_NPI_PREFIX_BATCHES):
                prefix = f"{batch:02d}"
                self._insert_spending_batch(
                    conn,
                    source_sql,
                    prefix,
                    billing_name_sql,
                    servicing_name_sql,
                    beneficiaries_sql,
                    claims_sql,
                    paid_sql,
                )
                conn.execute("CHECKPOINT")
                if batch % 10 == 9 or batch == SPENDING_NPI_PREFIX_BATCHES - 1:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM medicare_provider_spending"
                    ).fetchone()[0]
                    msg = (
                        f"  medicare_provider_spending: {count:,} rows "
                        f"(batch {batch + 1}/{SPENDING_NPI_PREFIX_BATCHES})"
                    )
                    log_info(msg)
                    print(msg, flush=True)

            count = conn.execute("SELECT COUNT(*) FROM medicare_provider_spending").fetchone()[0]
            named = conn.execute(
                """
                SELECT COUNT(*) FROM medicare_provider_spending
                WHERE billing_provider_name IS NOT NULL
                """
            ).fetchone()[0]
            self._save_ingest_marker(marker, source_path)
            log_info(
                f"  medicare_provider_spending: {count:,} rows "
                f"({named:,} with billing provider name from NPPES)"
            )
            print(
                f"  medicare_provider_spending: {count:,} rows "
                f"({named:,} with billing provider name from NPPES)",
                flush=True,
            )
            return count

    def _ingest_current(self, table: str, source: Path, marker: Path) -> bool:
        if not marker.exists():
            return False
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if meta.get("source") != str(source.resolve()):
            return False
        if meta.get("size") != source.stat().st_size:
            return False
        if meta.get("mtime") != source.stat().st_mtime:
            return False
        try:
            count = self.db_ops.execute_query(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            return False
        if count > 0:
            log_info(f"Skipping {table} ingest — source unchanged ({count:,} rows)")
            return True
        return False

    def _save_ingest_marker(self, marker: Path, source: Path) -> None:
        st = source.stat()
        marker.write_text(
            json.dumps(
                {
                    "source": str(source.resolve()),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
            ),
            encoding="utf-8",
        )