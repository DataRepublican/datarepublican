#!/usr/bin/env python3
"""
bmf_processor.py - BMF producer/consumer (1 producer + 1 consumer pattern)
"""

import subprocess
from pathlib import Path
from typing import Optional
import threading

from database_operations import DatabaseOperations
from pending_database_context import PendingDatabaseContext
from models.irsbmf import IrsBmf
from logging_utils import log_info, log_error
from base_processor import BaseProcessor, WorkUnit
from config import global_config
from database_operations import DatabaseOperation, DatabaseOperationType


class BmfProducer(BaseProcessor):
    """Producer thread: builds small PDC contexts and puts them on the queue."""

    def __init__(self, db_ops: DatabaseOperations):
        super().__init__(db_ops)
        self.bmf_dir = Path(global_config.zips_dir) / "bmf"
        self.bmf_dir.mkdir(parents=True, exist_ok=True)
    
    def _ensure_bmf_table(self):
        """Idempotent: download as .csv.gz, ingest directly from .gz if needed."""
        # 1. Download any missing .gz files
        missing = []
        for i in range(1, 5):
            gz_path = self.bmf_dir / f"eo{i}.csv.gz"
            if not gz_path.exists():
                missing.append(i)

        if not missing:
            log_info("All BMF .csv.gz files already exist – skipping download")
        else:
            log_info(f"Downloading {len(missing)} missing BMF files...")
            for i in missing:
                csv_path = self.bmf_dir / f"eo{i}.csv"
                gz_path = self.bmf_dir / f"eo{i}.csv.gz"

                url = f"https://www.irs.gov/pub/irs-soi/eo{i}.csv"
                log_info(f"Downloading eo{i}.csv...")

                # Download directly as .csv
                subprocess.run(["curl", "-L", "-o", str(csv_path), url], check=True)

                # Then gzip it to save space
                log_info(f"Compressing eo{i}.csv to save space...")
                subprocess.run(["gzip", "-f", str(csv_path)], check=True)

                log_info(f"eo{i}.csv downloaded and compressed successfully")

        # 2. Check if BMF table exists and has data
        with self.db_ops.acquire_write_conn() as conn:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='BMF'"
            ).fetchone()

            if table_exists:
                count = conn.execute("SELECT COUNT(*) FROM BMF").fetchone()[0]
                if count > 0:
                    log_info(f"BMF table already has {count:,} records – skipping ingest")
                    return

            # Table is missing or empty → ingest
            log_info("BMF table is missing or empty – ingesting directly from .gz files...")

            conn.execute("DROP TABLE IF EXISTS BMF;")
            conn.execute("""CREATE TABLE BMF (
                EIN VARCHAR PRIMARY KEY, NAME VARCHAR, ICO VARCHAR, STREET VARCHAR,
                CITY VARCHAR, STATE VARCHAR, ZIP VARCHAR, group_code VARCHAR,
                SUBSECTION VARCHAR, AFFILIATION BIGINT, CLASSIFICATION VARCHAR,
                RULING VARCHAR, DEDUCTIBILITY BIGINT, FOUNDATION VARCHAR,
                ACTIVITY VARCHAR, ORGANIZATION BIGINT, STATUS VARCHAR,
                TAX_PERIOD BIGINT, ASSET_CD BIGINT, INCOME_CD BIGINT,
                FILING_REQ_CD VARCHAR, PF_FILING_REQ_CD BIGINT, ACCT_PD VARCHAR,
                asset_amt DECIMAL(18,2), income_amt DECIMAL(18,2),
                revenue_amt DECIMAL(18,2), NTEE_CD VARCHAR, SORT_NAME VARCHAR,
                source_file VARCHAR
            );""")

            for i in range(1, 5):
                gz_path = self.bmf_dir / f"eo{i}.csv.gz"
                if gz_path.exists():
                    log_info(f"Ingesting eo{i}.csv.gz directly...")
                    conn.execute(f"""
                        INSERT INTO BMF 
                        SELECT *, '{gz_path}' FROM read_csv_auto('{gz_path}', header=true, compression='gzip');
                    """)

            conn.commit()
            final_count = conn.execute("SELECT COUNT(*) FROM BMF").fetchone()[0]
            log_info(f"BMF ingest complete – loaded {final_count:,} records")
    
    def _feed_thread(self, work_queue, max_files: Optional[int], num_producers: int):
        """Producer thread: builds small batches and puts them on the queue."""
        self._ensure_bmf_table()

        last_ein = self.db_ops.get_last_bmf_ein()
        if last_ein:
            log_info(f"Resuming BMF processing from EIN > {last_ein}")
        else:
            log_info("Starting fresh BMF processing (no prior IrsBmf records found)")

        processed = 0
        batch_size = 1000   # Small batches for memory safety

        while True:
            if max_files and processed >= max_files:
                break

            query = """
                SELECT EIN, NAME, ICO, STREET, CITY, STATE, ZIP, group_code, SUBSECTION,
                       AFFILIATION, CLASSIFICATION, RULING, DEDUCTIBILITY, FOUNDATION,
                       ACTIVITY, ORGANIZATION, STATUS, TAX_PERIOD, ASSET_CD, INCOME_CD,
                       FILING_REQ_CD, PF_FILING_REQ_CD, ACCT_PD, asset_amt, income_amt,
                       revenue_amt, NTEE_CD, SORT_NAME, source_file
                FROM BMF
            """
            params = []

            if last_ein is not None:
                query += " WHERE EIN > ?"
                params.append(last_ein)

            query += " ORDER BY EIN LIMIT ?"
            params.append(batch_size)

            rows = self.db_ops.execute_query(query, tuple(params)).fetchall()
            if not rows:
                break

            # Build one small context per batch
            context = PendingDatabaseContext()

            for row in rows:
                bmf = IrsBmf(
                    ein=row[0] or "", name=row[1] or "", ico=row[2],
                    group_code=row[7], subsection=row[8], affiliation=row[9],
                    classification=row[10], ruling=row[11], deductibility=row[12],
                    foundation=row[13], activity=row[14], organization=row[15],
                    status=row[16], tax_period=row[17], asset_cd=row[18],
                    income_cd=row[19], filing_req_cd=row[20],
                    pf_filing_req_cd=row[21], acct_pd=row[22],
                    asset_amt=row[23], income_amt=row[24], revenue_amt=row[25],
                    ntee_cd=row[26], sort_name=row[27], source_file=row[28]
                )
                bmf.prep_for_insert()

                address = bmf.build_address(
                    street=row[3], city=row[4], state=row[5], zip_code=row[6]
                )

                context.addObjectToDatabase(bmf)
                context.addObjectToDatabase(address)

                # Progress bar tick
                context.addOperationToDatabase(DatabaseOperation(
                    DatabaseOperationType.PROGRESS_UPDATE, {"count": 1}
                ))

                processed += 1
                if max_files and processed >= max_files:
                    break

            work_queue.put(WorkUnit.batch(context))   # Send batch to consumer
            last_ein = rows[-1][0]

        # Send sentinels to tell consumer we're done
        for i in range(num_producers):
            work_queue.put(WorkUnit.sentinel(i))

        log_info(f"BmfProducer completed – sent {processed:,} records in batches")


class BmfConsumer(BaseProcessor):
    """Consumer thread: pulls contexts from queue and saves them."""

    def _consumer_worker(self, result_queue, thread_id: int, num_producers: int):
        sentinels_received = 0
        while sentinels_received < num_producers:
            item = result_queue.get()

            if item.is_sentinel():
                sentinels_received += 1
                result_queue.task_done()
                continue

            if item.type == 'batch':
                context: PendingDatabaseContext = item.data
                context.save_to_database(self.db_ops)
                log_info(f"Consumer saved a batch of {context.getTotalObjectCount():,} records")

            result_queue.task_done()


class BmfProcessor(BaseProcessor):
    """Main BMF processor – 1 producer + 1 consumer pattern."""

    def __init__(self, db_ops: DatabaseOperations):
        super().__init__(db_ops)
        self.producer = BmfProducer(db_ops)
        self.consumer = BmfConsumer(db_ops)

    def fetch_and_ingest(self, max_files: Optional[int] = None) -> int:
        """Entry point – uses 1-producer + 1-consumer pattern."""
        global_config.max_files = max_files

        # For BMF we use a simple single-producer + single-consumer setup
        # (you can expand to multiple producers later if needed)

        from queue import Queue
        work_queue = Queue()

        # Start producer thread
        producer_thread = threading.Thread(
            target=self.producer._feed_thread,
            args=(work_queue, max_files, 1),   # 1 producer
            name="BmfProducer"
        )
        producer_thread.start()

        # Start consumer thread
        consumer_thread = threading.Thread(
            target=self.consumer._consumer_worker,
            args=(work_queue, 0, 1),           # 1 consumer
            name="BmfConsumer"
        )
        consumer_thread.start()

        # Wait for both to finish
        producer_thread.join()
        consumer_thread.join()

        log_info("BMF processing completed")
        return 0   # We don't return a precise count here; check logs or add counter if needed