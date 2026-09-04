#!/usr/bin/env python3
"""
dot_processor.py - FMCSA Motor Carrier Census ingest.

Downloads Company Census CSV from data.transportation.gov (curl, idempotent),
streams rows into dot_carriers + Addresses (phy + mailing).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from database_operations import DatabaseOperations
from download_utils import discover_fmcsa_census_url, ensure_download
from logging_utils import log_info, log_warning
from models import Address, DotCarrier

BATCH_SIZE = 2_500
CHECKPOINT_EVERY_BATCHES = 10
PROGRESS_EVERY_BATCHES = 20
INSERT_BATCH_SIZE = 2_500
ADDRESS_INSERT_BATCH_SIZE = 1_000
CENSUS_FILENAME = "company_census.csv"
INGEST_VERSION = 1

_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})")


class DotProcessor:
    def __init__(self, db_ops: DatabaseOperations, data_dir: str | Path):
        self.db_ops = db_ops
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> Dict[str, int]:
        log_info("=== Starting DOT step (download → parse → promote) ===")
        stats = {"downloads": 0, "carriers": 0, "addresses": 0}

        csv_path = self._ensure_census_csv(stats)
        if csv_path is None:
            log_warning("No FMCSA census CSV available — skipping DOT ingest")
            return stats

        marker = self.data_dir / ".dot_census_ingest.json"
        if self._ingest_current(csv_path, marker):
            return self._existing_counts(stats)

        stats.update(self._promote_census(csv_path))
        self._save_ingest_marker(marker, csv_path)
        log_info(f"=== DOT complete: {stats} ===")
        return stats

    def _ensure_census_csv(self, stats: Dict[str, int]) -> Optional[Path]:
        dest = self.data_dir / CENSUS_FILENAME
        url = discover_fmcsa_census_url()
        try:
            if ensure_download(url, dest, timeout=0):
                stats["downloads"] += 1
        except RuntimeError as exc:
            log_warning(f"FMCSA census download failed: {exc}")
            if not dest.exists() or dest.stat().st_size == 0:
                return None
        return dest if dest.exists() and dest.stat().st_size > 0 else None

    def _ingest_current(self, source: Path, marker: Path) -> bool:
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
        if meta.get("ingest_version") != INGEST_VERSION:
            return False
        try:
            count = self.db_ops.execute_query(
                "SELECT COUNT(*) FROM dot_carriers"
            ).fetchone()[0]
        except Exception:
            return False
        if count > 0:
            log_info(f"Skipping DOT ingest — source unchanged ({count:,} carriers)")
            return True
        return False

    def _existing_counts(self, stats: Dict[str, int]) -> Dict[str, int]:
        stats["carriers"] = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM dot_carriers"
        ).fetchone()[0]
        stats["addresses"] = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM Addresses WHERE address_type LIKE 'dot_carrier_%'"
        ).fetchone()[0]
        return stats

    def _save_ingest_marker(self, marker: Path, source: Path) -> None:
        st = source.stat()
        marker.write_text(
            json.dumps(
                {
                    "source": str(source.resolve()),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "ingest_version": INGEST_VERSION,
                }
            ),
            encoding="utf-8",
        )

    def _existing_carrier_rows(self, conn) -> int:
        row = conn.execute("SELECT COUNT(*) FROM dot_carriers").fetchone()
        return int(row[0]) if row else 0

    def _promote_census(self, csv_path: Path) -> Dict[str, int]:
        log_info(f"Ingesting FMCSA census from {csv_path} (streaming)")
        print(f"Ingesting FMCSA census from {csv_path} (streaming)", flush=True)

        run_totals = {"carriers": 0, "addresses": 0}
        carrier_batch: List[DotCarrier] = []
        address_batch: List[Address] = []
        batch_num = 0

        with self.db_ops.acquire_write_conn() as conn:
            self._ensure_dot_schema(conn)
            self._prepare_dot_conn(conn)
            existing = self._existing_carrier_rows(conn)
            skip_rows = 0
            if existing:
                skip_rows = existing
                msg = (
                    f"  DOT: resuming — skip {skip_rows:,} file rows, "
                    f"keep existing {existing:,} DB rows"
                )
                log_info(msg)
                print(msg, flush=True)
            else:
                self._clear_dot_tables(conn)

            skipped = 0
            with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                for raw_row in reader:
                    row = {
                        str(k or "").strip().lower(): (v or "").strip()
                        for k, v in raw_row.items()
                    }
                    carrier, addresses = self._row_to_models(row)
                    if carrier is None:
                        continue
                    if skipped < skip_rows:
                        skipped += 1
                        continue

                    carrier_batch.append(carrier)
                    address_batch.extend(addresses)

                    if len(carrier_batch) >= BATCH_SIZE:
                        batch_num += 1
                        run_totals = self._flush_batches(
                            conn, carrier_batch, address_batch, run_totals
                        )
                        carrier_batch.clear()
                        address_batch.clear()
                        if batch_num % CHECKPOINT_EVERY_BATCHES == 0:
                            conn.execute("CHECKPOINT")
                            log_info(
                                f"  DOT checkpoint after "
                                f"{existing + run_totals['carriers']:,} carriers"
                            )
                        if batch_num % PROGRESS_EVERY_BATCHES == 0:
                            msg = (
                                f"  DOT: +{run_totals['carriers']:,} this run "
                                f"({existing + run_totals['carriers']:,} total)"
                            )
                            log_info(msg)
                            print(msg, flush=True)

            if carrier_batch:
                run_totals = self._flush_batches(
                    conn, carrier_batch, address_batch, run_totals
                )
            conn.execute("CHECKPOINT")

        totals = {
            "carriers": existing + run_totals["carriers"],
            "addresses": self._existing_address_rows(),
        }
        log_info(f"  dot_carriers: {totals['carriers']:,}")
        log_info(f"  dot addresses: {totals['addresses']:,}")
        print(f"  dot_carriers: {totals['carriers']:,}", flush=True)
        print(f"  dot addresses: {totals['addresses']:,}", flush=True)
        return totals

    def _existing_address_rows(self) -> int:
        row = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM Addresses WHERE address_type LIKE 'dot_carrier_%'"
        ).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _prepare_dot_conn(conn) -> None:
        conn.execute("SET preserve_insertion_order=false")
        conn.execute("SET threads=2")
        conn.execute("SET memory_limit='12GB'")

    def _flush_batches(
        self,
        conn,
        carriers: List[DotCarrier],
        addresses: List[Address],
        totals: Dict[str, int],
    ) -> Dict[str, int]:
        if carriers:
            self.db_ops.bulk_insert(
                carriers,
                conn=conn,
                batch_size=INSERT_BATCH_SIZE,
                commit_batches=True,
            )
            totals["carriers"] += len(carriers)
            conn.execute("CHECKPOINT")
        if addresses:
            self.db_ops.bulk_insert(
                addresses,
                conn=conn,
                batch_size=ADDRESS_INSERT_BATCH_SIZE,
                commit_batches=True,
            )
            totals["addresses"] += len(addresses)
        return totals

    def _clear_dot_tables(self, conn) -> None:
        conn.execute(
            "DELETE FROM Addresses WHERE address_type LIKE 'dot_carrier_%'"
        )
        conn.execute("DELETE FROM dot_carriers")

    def _ensure_dot_schema(self, conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dot_carriers (
                id UUID DEFAULT uuidv7() PRIMARY KEY,
                dot_number VARCHAR NOT NULL UNIQUE,
                legal_name VARCHAR,
                dba_name VARCHAR,
                status_code VARCHAR,
                carrier_operation VARCHAR,
                business_org_desc VARCHAR,
                phone VARCHAR,
                email_address VARCHAR,
                power_units INTEGER,
                truck_units INTEGER,
                fleetsize VARCHAR,
                docket1 VARCHAR,
                docket1prefix VARCHAR,
                mcs150_date DATE,
                add_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    @staticmethod
    def _parse_date(value: str) -> Optional[str]:
        if not value:
            return None
        digits = value.split()[0]
        match = _DATE_RE.match(digits)
        if not match:
            return None
        y, m, d = match.groups()
        return f"{y}-{m}-{d}"

    @staticmethod
    def _parse_int(value: str) -> Optional[int]:
        if not value or not value.isdigit():
            return None
        return int(value)

    @staticmethod
    def _normalize_zip(value: str) -> str:
        return value.replace(" ", "").strip()

    @staticmethod
    def _is_promotable_address(address: Address) -> bool:
        return bool((address.canonical_address or "").strip())

    def _build_location_address(
        self,
        carrier: DotCarrier,
        *,
        street: str,
        city: str,
        state: str,
        zip_code: str,
        address_type: str,
    ) -> Optional[Address]:
        if not any((street, city, state, zip_code)):
            return None
        address = carrier.build_address(
            address_line1=street,
            city=city,
            state=state,
            zip_code=self._normalize_zip(zip_code),
            address_type=address_type,
        )
        return address if self._is_promotable_address(address) else None

    def _row_to_models(self, row: Dict[str, str]) -> Tuple[Optional[DotCarrier], List[Address]]:
        dot_number = row.get("dot_number", "")
        if not dot_number:
            return None, []

        carrier = DotCarrier(
            dot_number=dot_number,
            legal_name=row.get("legal_name") or None,
            dba_name=row.get("dba_name") or None,
            status_code=row.get("status_code") or None,
            carrier_operation=row.get("carrier_operation") or None,
            business_org_desc=row.get("business_org_desc") or None,
            phone=row.get("phone") or row.get("cell_phone") or None,
            email_address=row.get("email_address") or None,
            power_units=self._parse_int(row.get("power_units", "")),
            truck_units=self._parse_int(row.get("truck_units", "")),
            fleetsize=row.get("fleetsize") or None,
            docket1=row.get("docket1") or None,
            docket1prefix=row.get("docket1prefix") or None,
            mcs150_date=self._parse_date(row.get("mcs150_date", "")),
            add_date=self._parse_date(row.get("add_date", "")),
        )
        carrier.prep_for_insert()

        addresses: List[Address] = []
        phy = self._build_location_address(
            carrier,
            street=row.get("phy_street", ""),
            city=row.get("phy_city", ""),
            state=row.get("phy_state", ""),
            zip_code=row.get("phy_zip", ""),
            address_type="dot_carrier_phy",
        )
        if phy is not None:
            addresses.append(phy)

        mail = self._build_location_address(
            carrier,
            street=row.get("carrier_mailing_street", ""),
            city=row.get("carrier_mailing_city", ""),
            state=row.get("carrier_mailing_state", ""),
            zip_code=row.get("carrier_mailing_zip", ""),
            address_type="dot_carrier_mail",
        )
        if mail is not None:
            if phy is None or (mail.canonical_address or "") != (phy.canonical_address or ""):
                addresses.append(mail)

        return carrier, addresses