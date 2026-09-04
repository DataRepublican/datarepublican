#!/usr/bin/env python3
"""
zip_processor.py - ZIP file processing for IRS 990 data

This module handles the processing of IRS ZIP files, including
downloading, listing contents, and registering files in the database.
Uses producer-consumer pattern for safe batch processing with DuckDB.
"""

import os
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional

# Import producer-consumer pattern classes
from base_processor import BaseProcessor, BaseProducer, BaseConsumer, ThreadPoolManager, ThreadPoolConfig, PoolConfig
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from models import ZipFile, XMLFile
from logging_utils import start_progress_reporting, stop_progress_reporting, update_progress, log_info, log_debug, log_error, log_warning
from config import global_config
from pending_database_context import PendingDatabaseContext


class ZipProducer(BaseProducer):
    """Producer for ZIP file processing operations"""

    def __init__(self, db_ops: DatabaseOperations, zips_dir: str):
        super().__init__(db_ops, batch_size=10)  # Process ZIPs in small batches
        self.zips_dir = zips_dir

    def get_progress_scope(self, bytes: bool = False) -> Dict[str, Any]:
        """Get the scope of work for progress bar setup"""
        # For ZIP processing, we don't have a fixed total, so return unknown
        return {"total": None, "unit": "zips"}

    def _get_work_batch(self, offset: int) -> List[Path]:
        """Get a batch of ZIP files to process"""
        # For ZIP processing, we process all files in a directory
        # This is a simple implementation - get all ZIP files
        zip_files = []
        for zip_path in Path(self.zips_dir).glob("*.zip"):
            # Check if ZIP file is already processed
            zip_filename = zip_path.name
            existing_zip = self.db_ops.execute_query(
                "SELECT status FROM ZipFiles WHERE filename = ?",
                (zip_filename,)
            ).fetchone()

            if not existing_zip or existing_zip[0] != 'processed':
                # Also check if the file is within the year range if specified
                # The year filtering should be done at the processor level, not here
                zip_files.append(zip_path)

        # Apply offset and batch size
        start_idx = offset
        end_idx = start_idx + self.batch_size
        batch = zip_files[start_idx:end_idx] if start_idx < len(zip_files) else []

        return batch

    def _process_work_batch_to_context(self, batch: List[Path]) -> Optional['PendingDatabaseContext']:
        from pending_database_context import PendingDatabaseContext

        if not batch:
            return None

        # Create a single master context for the batch
        master_context = PendingDatabaseContext()
        # Existing ZipFiles rows that only need XmlFiles + a status flip after save
        self._zips_to_mark_processed: List[str] = getattr(self, "_zips_to_mark_processed", [])

        for zip_path in batch:
            # Check if ZIP file already exists in database
            zip_filename = zip_path.name
            existing_zip = self.db_ops.execute_query(
                "SELECT zip_id, status FROM ZipFiles WHERE filename = ?",
                (zip_filename,)
            ).fetchone()

            if existing_zip and existing_zip[1] == 'processed':
                # ZIP file already fully registered, skip it
                continue

            # Create ZipFile using factory method
            tax_year = int(zip_path.name[:4]) if zip_path.name[:4].isdigit() else 0
            zip_file = ZipFile.create_from_path(str(zip_path), tax_year)

            if existing_zip:
                zip_id = existing_zip[0]
                zip_file.zip_id = zip_id
                # If XmlFiles were already registered, never re-INSERT them —
                # that hits UNIQUE(zip_id, filename). Just flip status.
                existing_xml_count = self.db_ops.execute_query(
                    "SELECT COUNT(*) FROM XmlFiles WHERE zip_id = ?",
                    (zip_id,),
                ).fetchone()[0]
                if existing_xml_count and existing_xml_count > 0:
                    log_info(
                        f"ZIP {zip_filename} already has {existing_xml_count:,} "
                        f"XmlFiles — marking status=processed (no re-insert)"
                    )
                    self.db_ops.update_zip_status(str(zip_id), "processed")
                    continue
                # Zip row exists but members never registered (e.g. partial prior run)
                self._zips_to_mark_processed.append(str(zip_id))
            else:
                # New ZIP file, add to context for insertion
                zip_file.prep_for_insert()  # Generate zip_id
                # Root cause fix: land as processed so re-runs skip this archive
                zip_file.mark_processed()
                master_context.addObjectToDatabase(zip_file)

            # Extract XML file listing and sizes in one pass
            xml_sizes = ZipProcessor._get_all_xml_sizes_static(zip_path)
            xml_files = list(xml_sizes.keys())

            # Create XML file objects and add to context
            for xml_filename in xml_files:
                xml_file = zip_file.create_xml_file(
                    filename=xml_filename,
                    internal_path=xml_filename,
                    file_size=xml_sizes[xml_filename]
                )
                xml_file.prep_for_insert()  # Generate xml_id
                master_context.addObjectToDatabase(xml_file)

            log_info(
                f"Queuing {len(xml_files):,} XmlFiles for {zip_filename} "
                f"(zip_id={zip_file.zip_id})"
            )

        return master_context


class ZipConsumer(BaseConsumer):
    """Consumer for ZIP file operations"""

    def __init__(self, db_ops: DatabaseOperations, zips_dir: str):
        super().__init__(db_ops)
        self.zips_dir = zips_dir

    def _process_operations_batch(self, operations_by_type):
        """Process ZIP file operations using standardized pattern"""
        # All operations are now handled by PendingDatabaseContext.save_to_database()
        # which executes all operations directly
        pass

    def _execute_zip_operation(self, operation):
        """Execute a ZIP file operation"""
        data = operation.data
        zip_path_str = data["zip_path"]
        zips_dir = data["zips_dir"]
        operation_type = data["operation"]

        if operation_type == "process_zip_contents":
            zip_path = Path(zip_path_str)
            self._process_single_zip(zip_path)

    def _execute_operations_batch(self, operations):
        """Execute a batch of operations using the consumer pattern"""
        # All operations are now handled by the base class execute_operations_batch method
        # which properly groups and executes operations in dependency order
        self.execute_operations_batch(operations)


class ZipProcessor:
    """Main processor for ZIP file processing using producer-consumer pattern"""

    def __init__(self, db_ops: DatabaseOperations, zips_dir: str):
        self.db_ops = db_ops
        self.zips_dir = zips_dir

        # Initialize producer and consumer
        self.producer = ZipProducer(db_ops, zips_dir)
        self.consumer = ZipConsumer(db_ops, zips_dir)

        # Initialize thread pool manager
        thread_config = ThreadPoolConfig(
            producer_config=PoolConfig(max_workers=2, queue_size=20),  # Process 2 ZIPs at a time
            consumer_config=PoolConfig(max_workers=1, queue_size=10)   # Single consumer for DB safety
        )
        self.thread_pool_manager = ThreadPoolManager(thread_config, self)

    # Small chunks: full-zip bulk insert OOMs on the 94GB production DB even at 16GB limit.
    XML_REGISTER_CHUNK = 2000

    def process_zip_files(self, start_year: int, end_year: int) -> List[Path]:
        """Register ZIP archives and their XmlFiles members (chunked inserts)."""
        log_info(
            f"Processing ZIP files from {start_year} to {end_year} "
            f"(chunked XmlFiles inserts, size={self.XML_REGISTER_CHUNK})"
        )

        try:
            # Repair prior runs that registered XmlFiles but left status='downloaded'
            self._mark_registered_zips_processed()

            zip_files = self._list_zips_in_year_range(start_year, end_year)
            if not zip_files:
                log_info("No ZIP files to process")
                return []

            total_xml = 0
            for zip_path in zip_files:
                log_info(f"Registering ZIP: {zip_path.name}")
                n = self._register_one_zip_chunked(zip_path)
                total_xml += n
                log_info(f"Finished registering {zip_path.name} (+{n:,} XmlFiles)")

            self._mark_registered_zips_processed()
            log_info(f"ZIP file processing complete: {total_xml:,} XmlFiles inserted this run")
            return []

        except Exception as e:
            log_error(f"ZIP processing failed: {e}", exc_info=True)
            return []

    def _list_zips_in_year_range(self, start_year: int, end_year: int) -> List[Path]:
        """ZIP paths under zips_dir whose filename year is in [start_year, end_year]."""
        zip_files: List[Path] = []
        for zip_path in sorted(Path(self.zips_dir).glob("*.zip")):
            filename_year_str = zip_path.name[:4]
            if filename_year_str.isdigit():
                filename_year = int(filename_year_str)
                if start_year <= filename_year <= end_year:
                    zip_files.append(zip_path)
        return zip_files

    def _register_one_zip_chunked(self, zip_path: Path) -> int:
        """Register one archive's members in small committed batches. Returns XmlFiles inserted."""
        zip_filename = zip_path.name
        existing = self.db_ops.execute_query(
            "SELECT zip_id, status FROM ZipFiles WHERE filename = ?",
            (zip_filename,),
        ).fetchone()

        if existing and existing[1] == "processed":
            log_info(f"Skipping {zip_filename} — already status=processed")
            return 0

        tax_year = int(zip_filename[:4]) if zip_filename[:4].isdigit() else 0
        zip_file = ZipFile.create_from_path(str(zip_path), tax_year)

        if existing:
            zip_id = existing[0]
            zip_file.zip_id = zip_id
        else:
            zip_file.prep_for_insert()
            zip_file.mark_processed()  # will be true after members land; status set again at end
            # Insert zip row alone first (tiny)
            self.db_ops.bulk_insert([zip_file], batch_size=1, commit_batches=True)
            zip_id = zip_file.zip_id

        zip_id_str = str(zip_id)

        # Members already on disk listing
        xml_sizes = self._get_all_xml_sizes_static(zip_path)
        all_names = list(xml_sizes.keys())
        if not all_names:
            log_warning(f"{zip_filename}: no .xml members — marking processed")
            self.db_ops.update_zip_status(zip_id_str, "processed")
            return 0

        # Skip names already registered (resume after partial OOM)
        existing_names = {
            r[0]
            for r in self.db_ops.execute_query(
                "SELECT filename FROM XmlFiles WHERE zip_id = ?",
                (zip_id,),
            ).fetchall()
        }
        pending = [n for n in all_names if n not in existing_names]
        log_info(
            f"{zip_filename}: {len(all_names):,} members, "
            f"{len(existing_names):,} already registered, {len(pending):,} to insert"
        )
        if not pending:
            self.db_ops.update_zip_status(zip_id_str, "processed")
            return 0

        inserted = 0
        chunk = self.XML_REGISTER_CHUNK
        for i in range(0, len(pending), chunk):
            batch_names = pending[i : i + chunk]
            objs = []
            for xml_filename in batch_names:
                xml_file = zip_file.create_xml_file(
                    filename=xml_filename,
                    internal_path=xml_filename,
                    file_size=xml_sizes[xml_filename],
                )
                xml_file.prep_for_insert()
                objs.append(xml_file)
            self.db_ops.bulk_insert(objs, batch_size=chunk, commit_batches=True)
            inserted += len(objs)
            log_info(
                f"{zip_filename}: inserted {inserted:,}/{len(pending):,} "
                f"(chunk {i // chunk + 1})"
            )

        self.db_ops.update_zip_status(zip_id_str, "processed")
        return inserted

    def _mark_registered_zips_processed(self) -> int:
        """Set status=processed for ZipFiles that already have XmlFiles rows.

        Root-cause repair: skip logic keys off status=='processed', but older runs
        left status at 'downloaded' forever, so every zip re-ran and re-INSERTed
        members into UNIQUE(zip_id, filename).
        """
        result = self.db_ops.execute_query(
            """
            SELECT COUNT(*) FROM ZipFiles z
            WHERE (z.status IS NULL OR z.status != 'processed')
              AND EXISTS (SELECT 1 FROM XmlFiles x WHERE x.zip_id = z.zip_id)
            """
        ).fetchone()
        n = int(result[0]) if result else 0
        if n <= 0:
            return 0
        self.db_ops.execute_query(
            """
            UPDATE ZipFiles z
            SET status = 'processed',
                processed_date = CURRENT_TIMESTAMP
            WHERE (z.status IS NULL OR z.status != 'processed')
              AND EXISTS (SELECT 1 FROM XmlFiles x WHERE x.zip_id = z.zip_id)
            """
        )
        self.db_ops.commit()
        log_info(f"Marked {n:,} ZipFiles as processed (already had XmlFiles registered)")
        return n

    def _producer_wrapper(self, zip_files: List[Path], work_queue, result_queue, thread_id: int, num_threads: int):
        """Wrapper for producer thread execution"""
        try:
            log_debug(f"ZIP Producer thread {thread_id} starting")

            # Distribute work items among threads
            for i in range(thread_id, len(zip_files), num_threads):
                zip_path = zip_files[i]

                # Create operation to process this ZIP file
                operation = DatabaseOperation(
                    operation_type=DatabaseOperationType.INSERT_ZIP_FILE,
                    data={
                        "zip_path": str(zip_path),
                        "zips_dir": self.zips_dir,
                        "operation": "process_zip_contents"
                    }
                )

                # Put operation in result queue for consumer
                result_queue.put(operation)

                log_debug(f"ZIP Producer {thread_id}: queued operation for {zip_path.name}")

        except Exception as e:
            log_error(f"ZIP Producer thread {thread_id} error: {e}", exc_info=True)
        finally:
            # Signal completion
            result_queue.put(None)

    def _collect_contexts_with_year_filter(self, start_year: int, end_year: int) -> Optional['PendingDatabaseContext']:
        """Collect ZIP files filtered by year range and create a PendingDatabaseContext.

        Prefer process_zip_files() which registers one archive at a time to avoid OOM.
        """
        zip_files = self._list_zips_in_year_range(start_year, end_year)
        if not zip_files:
            return None
        return self.producer._process_work_batch_to_context(zip_files)

    def _consumer_wrapper(self, result_queue, thread_id: int, num_producers: int, progress_bar=None):
        """Wrapper for consumer thread execution"""
        try:
            log_debug(f"ZIP Consumer thread {thread_id} starting")
            sentinels_received = 0

            while True:
                try:
                    operation = result_queue.get(timeout=1.0)
                    if operation is None:  # Sentinel
                        sentinels_received += 1
                        if sentinels_received >= num_producers:
                            break
                        continue

                    # Execute the operation
                    if isinstance(operation, DatabaseOperation):
                        self.consumer._execute_zip_operation(operation)

                        # Update progress
                        if progress_bar:
                            progress_bar.update(1)

                    result_queue.task_done()

                except:
                    continue

        except Exception as e:
            log_error(f"ZIP Consumer thread {thread_id} error: {e}", exc_info=True)

    def _process_single_zip(self, zip_path: Path):
        """Process a single ZIP file"""
        zip_filename = zip_path.name
        zip_year = int(zip_filename[:4]) if zip_filename[:4].isdigit() else 0

        # Create ZipFile object
        zip_file = ZipFile(
            filename=zip_filename,
            file_path=str(zip_path),
            tax_year=zip_year,
            file_size=zip_path.stat().st_size if zip_path.exists() else None,
            status='downloaded'
        )

        # Use filename + size as simple integrity check (no checksum needed)
        if zip_path.exists():
            zip_file.checksum = f"{zip_path.name}:{zip_path.stat().st_size}"

        # Create PDC context for this ZIP processing
        from pending_database_context import PendingDatabaseContext
        context = PendingDatabaseContext()

        # Extract XML file listing and sizes in one pass
        xml_sizes = self._get_all_xml_sizes(zip_path)
        xml_files = list(xml_sizes.keys())
        print(f"Found {len(xml_files)} XML files")

        # DEBUG: Log XML file details for validation
        print(f"DEBUG: ZIP {zip_filename} - XML files found: {len(xml_files)}")
        if xml_files:
            print(f"DEBUG: First 5 XML files: {xml_files[:5]}")
            print(f"DEBUG: XML file sizes: {list(xml_sizes.values())[:5]}")

        zip_file.mark_processed()
        # Add ZIP file to context
        context.addObjectToDatabase(zip_file)

        # Create XML file objects and add to context
        for xml_filename in xml_files:
            xml_file = zip_file.create_xml_file(
                filename=xml_filename,
                internal_path=xml_filename,
                file_size=xml_sizes[xml_filename]
            )
            context.addObjectToDatabase(xml_file)

        # Execute the context operations directly
        context.save_to_database(self.db_ops)

        # Get the zip_id from the database after PDC execution
        result = self.db_ops.execute_query(
            "SELECT zip_id FROM ZipFiles WHERE filename = ? ORDER BY zip_id DESC LIMIT 1",
            (zip_filename,)
        ).fetchone()
        zip_id = result[0] if result else None

        if zip_id:
            log_info(f"Registered ZIP file: {zip_filename} (ID: {zip_id}, status=processed)")
        else:
            log_warning(f"Could not determine zip_id for {zip_filename}")

    def _get_xml_files_from_zip(self, zip_path: Path) -> List[str]:
        """Get XML files from ZIP"""
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Get XML files from ZIP
            xml_files = [f for f in zip_ref.namelist() if f.endswith('.xml')]
        return xml_files

    @staticmethod
    def _get_all_xml_sizes_static(zip_path: Path) -> dict:
        """Get all XML file sizes from ZIP in one pass, handling corrupt files gracefully"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                xml_sizes = {}
                for info in zip_ref.filelist:
                    if info.filename.endswith('.xml'):
                        xml_sizes[info.filename] = info.file_size
                print(f"DEBUG: ZIP {zip_path.name} - Sized {len(xml_sizes)} XML files from ZIP {zip_path.name}")
                return xml_sizes
        except zipfile.BadZipFile as e:
            print(f"Corrupt ZIP file {zip_path}: {e}")
            return {}
        except Exception as e:
            print(f"Error reading ZIP file {zip_path}: {e}")
            return {}
