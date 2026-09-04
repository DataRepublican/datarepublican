#!/usr/bin/env python3
"""
xml_processor.py - XML file processing for IRS 990 data

This module handles the parsing and processing of IRS 990 XML files,
extracting data into dataclasses and storing in the database.
"""

import time
import threading
import queue
from io import BytesIO
from typing import Optional, List, Tuple, Dict, Any
from lxml import etree  # type: ignore
import psutil
import zipfile
from enum import Enum

from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from models import Charity, Officer, Grant, Contractor, PoliticalContribution, Address
from pending_database_context import PendingDatabaseContext
from base_processor import BaseProcessor, WorkUnit
import parse_990
import parse_990ez
import parse_990pf
from logging_utils import log_info, log_error, log_debug, log_warning, dump_traceback
from typing import Optional, List, Tuple
from config import global_config
from constants import CURRENT_PROCESSING_VERSION, CONSUMER_BATCH_SIZE, MONITOR_INTERVAL_SECONDS
from datetime import datetime

from collections import deque
# Import XPath configurations from xpaths.py
from xpaths import COMMON_XPATHS, tostring, HEADER_UNION_XPATH
from xpaths_990 import XPATHS_990
from xpaths_990ez import XPATHS_990EZ
from xpaths_990pf import XPATHS_990PF

DEBUG_TASK_FLOW = False


















class XMLProcessor(BaseProcessor):
    """
    XML Processor - Main entry point for XML processing operations.

    This class coordinates XML processing using the producer-consumer pattern.
    It can operate in both single-threaded and multi-threaded modes.
    """

    def __init__(self, db_ops: DatabaseOperations, processing_version: int = 1):
        super().__init__(db_ops)
        self.processing_version = processing_version

        # ZIP cache for XML processing
        self._zip_cache: Dict[str, zipfile.ZipFile] = {}
        self._zip_cache_lock = threading.Lock()
        self._zip_cache_ref_count: Dict[str, int] = {}

        # Initialize PDC attributes for status gauges
        self.pdc_objects_count = 0
        self.pdc_operations_count = 0
        self.pdc_updates_count = 0

        # Initialize separate PDC gauges
        self.pdc_objects_gauge = None
        self.pdc_operations_gauge = None
        self.pdc_updates_gauge = None

    def _get_custom_metrics(self) -> Dict[str, Any]:
        """Custom metrics for XMLProcessor."""
        try:
            return {
                'zip_cache_size': len(self._zip_cache),
                'pdc_objects_count': self.pdc_objects_count,
                'pdc_operations_count': self.pdc_operations_count,
                'pdc_updates_count': self.pdc_updates_count,
            }
        except AttributeError as e:
            # Handle missing attributes gracefully
            log_error(f"Error accessing custom metrics: {e}")
            return {}

    def _setup_pdc_gauges(self):
        """Setup separate tqdm gauges for each PDC metric."""
        try:
            import tqdm
            if tqdm:
                self.pdc_objects_gauge = tqdm.tqdm(
                    total=100,  # Percentage
                    desc="PDC Objects",
                    unit="%",
                    bar_format='{desc}: {postfix}',
                    position=3,  # Position below memory gauge
                    leave=True
                )
                self.pdc_operations_gauge = tqdm.tqdm(
                    total=100,  # Percentage
                    desc="PDC Operations",
                    unit="%",
                    bar_format='{desc}: {postfix}',
                    position=4,  # Position below objects gauge
                    leave=True
                )
                self.pdc_updates_gauge = tqdm.tqdm(
                    total=100,  # Percentage
                    desc="PDC Updates",
                    unit="%",
                    bar_format='{desc}: {postfix}',
                    position=5,  # Position below operations gauge
                    leave=True
                )
        except ImportError:
            pass

    def _update_pdc_gauges(self):
        """Update the PDC gauges with current values."""
        if self.pdc_objects_gauge:
            postfix = f"Count: {self.pdc_objects_count}"
            self.pdc_objects_gauge.set_postfix({"info": postfix})
            self.pdc_objects_gauge.refresh()

        if self.pdc_operations_gauge:
            postfix = f"Count: {self.pdc_operations_count}"
            self.pdc_operations_gauge.set_postfix({"info": postfix})
            self.pdc_operations_gauge.refresh()

        if self.pdc_updates_gauge:
            postfix = f"Count: {self.pdc_updates_count}"
            self.pdc_updates_gauge.set_postfix({"info": postfix})
            self.pdc_updates_gauge.refresh()

    def _on_shutdown(self):
        """Override for XML-specific shutdown cleanup."""
        self.cleanup_zip_cache()

        # Close PDC gauges
        if self.pdc_objects_gauge:
            self.pdc_objects_gauge.close()
        if self.pdc_operations_gauge:
            self.pdc_operations_gauge.close()
        if self.pdc_updates_gauge:
            self.pdc_updates_gauge.close()

    def process_xml_files(self, max_files: Optional[int] = None, workers: int = 4, collect_xpath_stats: bool = False) -> int:
        """
        Process XML files using parallel producer-consumer pattern.

        Args:
            max_files: Maximum number of files to process (for testing)
            workers: Number of worker threads for parallel processing

        Returns:
            Number of XML files processed
        """
        return self.process_parallel(max_files, workers)


    def get_work_count(self, max_files: Optional[int] = None) -> int:
        """Get the total number of XML files to process."""
        from constants import CURRENT_PROCESSING_VERSION
        return self.db_ops.get_xml_files_to_process_count(CURRENT_PROCESSING_VERSION) if max_files is None else max_files

    def get_progress_config(self, max_files: Optional[int] = None) -> Tuple[int, str, str]:
        """Get progress bar configuration for XML processing."""
        total = self.get_work_count(max_files)
        unit = "file" if global_config.progress == "files" else "B"
        desc = "Processing XML files" if global_config.progress == "files" else "XML bytes"
        return total, unit, desc

    def _feed_thread(self, work_queue: queue.Queue, max_files: Optional[int], num_producers: int):
        """Feeder thread: Fetches XML files and feeds into shared queue."""
        threading.current_thread().name = 'Feeder'
        from constants import CURRENT_PROCESSING_VERSION, BATCH_SIZE
        total_fed = 0
        last_xml_id = None

        while True:
            # Calculate batch size
            remaining = max_files - total_fed if max_files else BATCH_SIZE
            batch_size = min(BATCH_SIZE, remaining) if max_files else BATCH_SIZE

            # Fetch batch
            xml_files = self.db_ops.get_xml_files_to_process(
                processing_version=CURRENT_PROCESSING_VERSION,
                max_files=batch_size,
                last_xml_id=last_xml_id
            )

            if not xml_files:
                break

            # Enqueue each file individually
            for xml_file in xml_files:
                work_queue.put(WorkUnit.work_item(xml_file))
            total_fed += len(xml_files)

            # Update last_xml_id
            last_xml_id = max(f.xml_id for f in xml_files)

            if max_files and total_fed >= max_files:
                break

        # Send sentinels immediately after queuing all work
        log_info(f"Feeder completed queuing {total_fed} files, sending {num_producers} sentinels")
        for i in range(num_producers):
            work_queue.put(WorkUnit.sentinel(i))

    def _process_work_item(self, xml_file) -> PendingDatabaseContext:
        """Process a single XML file into a PendingDatabaseContext."""
        xml_id = xml_file.xml_id
        zip_id = xml_file.zip_id
        filename = xml_file.filename
        internal_path = xml_file.internal_path
        file_size = xml_file.file_size

        # Create context for this XML file processing
        context = PendingDatabaseContext(xml_id=xml_id)

        success = self._process_single_xml_with_context(xml_id, zip_id, filename, internal_path, context)

        # Add XML_FILE_UPDATE operation to context
        from database_operations import DatabaseOperation, DatabaseOperationType
        from constants import CURRENT_PROCESSING_VERSION

        metadata = {
            "file_size": file_size,
            "ein": context.getObjectsByType('charity')[0].ein if context.getObjectsByType('charity') else "Unknown",
            "tax_year": context.getObjectsByType('charity')[0].tax_year if context.getObjectsByType('charity') else None,
            "form_type": context.getObjectsByType('charity')[0].form_type if context.getObjectsByType('charity') else None,
            "error_message": context.error_message,  # Include error message if parsing failed
            "processed": True, # at least attempted
            "xml_id": xml_id,
            "processing_version": CURRENT_PROCESSING_VERSION
        }

        # If successful, populate metadata with actual parsed values from charity
        if not context.error_message and context.getObjectsByType('charity'):
            charity = context.getObjectsByType('charity')[0]
            metadata["form_type"] = charity.form_type
            metadata["tax_year"] = charity.tax_year
            metadata["ein"] = charity.ein
            metadata["org_type"] = charity.org_type
            metadata["error_message"] = "success"  # Set to "success" for successful processing

        # Create XML_FILE_UPDATE operation and add to context
        xml_update_op = DatabaseOperation(
            DatabaseOperationType.XML_FILE_UPDATE,
            metadata,
            xml_id=xml_id
        )
        context.addOperationToDatabase(xml_update_op)

        # Add PROGRESS_UPDATE operation per XML file
        progress_data = {"bytes": file_size} if global_config.progress == "bytes" else {"count": 1}
        progress_op = DatabaseOperation(
            DatabaseOperationType.PROGRESS_UPDATE,
            progress_data
        )
        context.addOperationToDatabase(progress_op)

        return context
        
    def _pdc_metrics(self, pdc: PendingDatabaseContext):
        self.pdc_objects_count = pdc.getTotalObjectCount()
        self.pdc_operations_count = pdc.getOperationsCount()
        self.pdc_updates_count = pdc.getUpdatesCount()

        # Update PDC gauges with new values
        self._update_pdc_gauges()
        
    def _process_single_xml_with_context(self, xml_id: str, zip_id: str, filename: str, internal_path: str, context: PendingDatabaseContext) -> bool:
        """
        Process a single XML file using the context-based approach.

        Args:
            xml_id: XML file ID
            zip_id: ZIP file ID (UUID string)
            filename: XML filename
            internal_path: Path within ZIP
            context: PendingDatabaseContext to collect objects

        Returns:
            bool: Success status
        """
        try:
            if not global_config.is_quiet():
                log_debug(f"Processing XML {filename} (ID: {xml_id})")

            # Validate zip_id is not a file path
            if zip_id and isinstance(zip_id, str) and ('/' in zip_id or '\\' in zip_id):
                raise ValueError(f"zip_id parameter contains file path instead of UUID: {zip_id}")

            # Clear context at the start of each XML file processing to ensure isolation
            context.clear()

            # Get ZIP file path from cache
            zip_path = self.db_ops.get_zip_file_path(zip_id)
            if not zip_path:
                if not global_config.is_quiet():
                    log_error(f"No ZIP file found for xml_id {xml_id}")
                return False

            # Extract XML content from ZIP using cached connection
            xml_content = self._extract_xml_from_zip(zip_path, internal_path)

            if not global_config.is_quiet():
                log_debug(f"Extracted XML content for {filename}, size: {len(xml_content)} bytes")

            # Parse XML
            parser = etree.XMLParser(recover=True)
            tree = etree.parse(BytesIO(xml_content), parser)
            root = tree.getroot()

            # Check exit_processing flag before continuing with expensive operations
            if BaseProcessor.exit_processing:
                log_info(f"Exiting thread due to exit_processing flag")
                print("EXITING PROCESSING")
                return False

            # Extract basic metadata using batch header extraction
            form_type, tax_year, filer_ein = self._extract_form_header_batch(root)

            if not global_config.is_quiet():
                log_debug(f"Extracted metadata for {filename}: form_type={form_type}, tax_year={tax_year}, ein={filer_ein}")

            if not filer_ein or filer_ein == "Unknown":
                if not global_config.is_quiet():
                    log_error(f"DEBUG: Skipping XML {filename}: invalid EIN {filer_ein} - this will create NULL EIN Charity!")
                return False

            # Create charity object first
            charity = Charity(
                ein=filer_ein,
                tax_year=tax_year,
                form_type=form_type,
                xml_name=filename
            )
            # Force ID generation before adding to context and parsing dependents
            charity.prep_for_insert()
            if not global_config.is_quiet():
                log_info(f"CREATING CHARITY: EIN {filer_ein}, tax_year {tax_year}, form_type {form_type}, xml_name {filename}")
            context.addObjectToDatabase(charity)

            # Use base parser factory to get the correct parser and parse the form
            from base_parser import BaseParser
            parser = BaseParser.create_parser(form_type)
            if parser:
                parser.parse_form(root, filename, {}, context, cached_charity=charity)
            else:
                if not global_config.is_quiet():
                    log_info(f"Unsupported form type {form_type} in {filename}")
                return False

            # Explicit cleanup after parsing
            del root, tree

            # Log grant collection results
            counts = context.getObjectCounts()
            if not global_config.is_quiet():
                log_info(f"PROCESSING COMPLETE: EIN {filer_ein} in {filename}: {counts['grant']} grants, {counts['contractor']} contractors, {counts['political_contribution']} contributions, {counts['officer']} officers, {counts['address']} addresses",
                          ein=filer_ein)

            if not global_config.is_quiet():
                log_debug(f"SUCCESS: Parsed {filename}: charity={filer_ein}, grants={counts['grant']}, officers={counts['officer']}, contractors={counts['contractor']}, contributions={counts['political_contribution']}, addresses={counts['address']}")
            return True

        except etree.XMLSyntaxError as e:
            if not global_config.is_quiet():
                log_error(f"FAILED: XML {filename}: XML syntax error - {e}")
            # Store specific error message for XML parsing issues
            import traceback
            error_msg = f"XML Syntax Error: {str(e)}\n\nStack Trace:\n{traceback.format_exc()}"
            context.error_message = error_msg
            return False
        except etree.ParseError as e:
            if not global_config.is_quiet():
                log_error(f"FAILED: XML {filename}: XML parse error - {e}")
            # Store specific error message for XML parsing issues
            import traceback
            error_msg = f"XML Parse Error: {str(e)}\n\nStack Trace:\n{traceback.format_exc()}"
            context.error_message = error_msg
            return False
        except zipfile.BadZipFile as e:
            if not global_config.is_quiet():
                log_error(f"FAILED: XML {filename}: Bad ZIP file - {e}")
            # Store specific error message for ZIP file issues
            import traceback
            error_msg = f"ZIP File Error: {str(e)}\n\nStack Trace:\n{traceback.format_exc()}"
            context.error_message = error_msg
            return False
        except ValueError as e:
            if not global_config.is_quiet():
                log_error(f"FAILED: XML {filename}: Value error - {e}")
            # Store specific error message for validation issues
            import traceback
            error_msg = f"Validation Error: {str(e)}\n\nStack Trace:\n{traceback.format_exc()}"
            context.error_message = error_msg
            return False
        except Exception as e:
            # Store error message with stack trace in context for unexpected errors
            import traceback
            error_msg = f"Unexpected Error: {str(e)}\n\nStack Trace:\n{traceback.format_exc()}"
            context.error_message = error_msg
            if not global_config.is_quiet():
                log_error("FAILED: XML {}: Unexpected error - {}\n{}", filename, str(e), traceback.format_exc())
            return False

    def _extract_form_header_batch(self, root) -> Tuple[str, int, str]:
        """
        Extract form header values (form_type, tax_year, filer_ein) in a single XPath evaluation.

        Returns:
            Tuple of (form_type, tax_year, filer_ein)
        """
        # Initialize defaults
        form_type = "Unknown"
        tax_year = 0
        filer_ein = None

        try:
            # Evaluate the union XPath once to get all header elements
            header_elements = HEADER_UNION_XPATH(root)

            # Process each element to extract the values
            for element in header_elements:
                tag_name = element.tag.split('}')[-1]  # Remove namespace prefix if present
                text_value = element.text.strip() if element.text else ""

                if tag_name in ("ReturnTypeCd", "ReturnType"):
                    # Validate against known IRS form types
                    valid_forms = {"990", "990EZ", "990PF", "990T"}
                    if text_value in valid_forms:
                        form_type = text_value
                    else:
                        # Log invalid form type but continue processing
                        if not global_config.is_quiet():
                            log_warning(f"Invalid form type '{text_value}' found, treating as Unknown")
                        form_type = "Unknown"

                elif tag_name in ("TaxYr", "TaxYear"):
                    if text_value and text_value.isdigit():
                        tax_year = int(text_value)

                elif tag_name == "EIN":
                    if text_value.isdigit():
                        formatted_ein = f"{int(text_value):09d}"
                        if not global_config.is_quiet():
                            log_info(f"TRACE: Formatted EIN: '{formatted_ein}' (valid 9-digit)")
                        filer_ein = formatted_ein
                    else:
                        if not global_config.is_quiet():
                            log_error(f"TRACE: Non-digit EIN found: '{text_value}', raising exception")
                        raise ValueError(f"Invalid EIN format: '{text_value}' - must be numeric")

        except Exception as e:
            log_debug(f"Header union XPath evaluation failed: {e}")
            # Fall back to individual extraction if batch fails
            form_type = self._extract_form_type(root)
            tax_year = self._extract_tax_year(root)
            filer_ein = self._extract_filer_ein(root)

        if not filer_ein:
            if not global_config.is_quiet():
                log_error("TRACE: No EIN found in XML, raising exception")
            raise ValueError("No EIN found in XML")

        return form_type, tax_year, filer_ein

    def _extract_form_type(self, root) -> str:
        """Extract form type from XML with validation"""
        for xpath in COMMON_XPATHS["form_type"]:
            try:
                result = xpath(root)
                if result and result[0].text:
                    form_type = result[0].text.strip()
                    # Validate against known IRS form types
                    valid_forms = {"990", "990EZ", "990PF", "990T"}
                    if form_type in valid_forms:
                        return form_type
                    else:
                        # Log invalid form type but continue processing
                        if not global_config.is_quiet():
                            log_warning(f"Invalid form type '{form_type}' found, treating as Unknown")
                        return "Unknown"
            except:
                continue
        return "Unknown"

    def _extract_tax_year(self, root) -> int:
        """Extract tax year from XML"""
        for xpath in COMMON_XPATHS["tax_year"]:
            try:
                result = xpath(root)
                if result:
                    year_str = result[0].text
                    if year_str and year_str.isdigit():
                        return int(year_str)
            except:
                continue
        return 0  # Default fallback

    def _extract_filer_ein(self, root) -> str:
        """Extract filer EIN from XML"""
        for xpath in COMMON_XPATHS["filer_ein"]:
            try:
                result = xpath(root)
                if result:
                    raw_ein = result[0].text.strip()
                    if not global_config.is_quiet():
                        log_info(f"TRACE: Found raw EIN: '{raw_ein}' using xpath: {xpath.path}")
                    if raw_ein.isdigit():
                        formatted_ein = f"{int(raw_ein):09d}"
                        if not global_config.is_quiet():
                            log_info(f"TRACE: Formatted EIN: '{formatted_ein}' (valid 9-digit)")
                        return formatted_ein
                    else:
                        if not global_config.is_quiet():
                            log_error(f"TRACE: Non-digit EIN found: '{raw_ein}', raising exception")
                        raise ValueError(f"Invalid EIN format: '{raw_ein}' - must be numeric")
            except Exception as e:
                log_debug(f"XPath {xpath.path} failed: {e}")
                continue
        if not global_config.is_quiet():
            log_error("TRACE: No EIN found in XML, raising exception")
        raise ValueError("No EIN found in XML")

    def _extract_xml_from_zip(self, zip_path: str, internal_path: str) -> bytes:
        """Extract XML content from ZIP using cached connection with reference counting"""
        import threading
        zip_key = str(zip_path)
        thread_id = threading.get_ident()

        # Extract from ZIP - no content caching since XML files are processed once
        log_debug(f"Thread {thread_id}: Requesting ZIP access for {zip_path} (key: {zip_key})")

        with self._zip_cache_lock:
            log_debug(f"Thread {thread_id}: Acquired ZIP cache lock for {zip_path}")
            if zip_key not in self._zip_cache:
                # Open ZIP file and cache the connection (ZipFile is thread-safe)
                log_info(f"Thread {thread_id}: Opening new ZIP connection for {zip_path}")
                zip_ref = zipfile.ZipFile(zip_path, 'r')
                self._zip_cache[zip_key] = zip_ref
                self._zip_cache_ref_count[zip_key] = 1
                log_info(f"Thread {thread_id}: Opened and cached ZIP connection for {zip_path}")
            else:
                # Increment reference count for existing connection
                self._zip_cache_ref_count[zip_key] += 1
                log_debug(f"Thread {thread_id}: Using cached ZIP connection for {zip_path} (ref_count: {self._zip_cache_ref_count[zip_key]})")

            zip_ref = self._zip_cache[zip_key]
            log_debug(f"Thread {thread_id}: Retrieved ZIP reference from cache for {zip_path}")
            log_debug(f"Thread {thread_id}: Releasing ZIP cache lock for {zip_path}")

        # Extract XML content from cached connection (ZipFile is thread-safe)
        log_debug(f"Thread {thread_id}: Starting extraction of {internal_path} from {zip_path}")
        try:
            log_debug(f"Thread {thread_id}: Opening {internal_path} in ZIP file")
            with zip_ref.open(internal_path) as xml_file:
                log_debug(f"Thread {thread_id}: Reading content from {internal_path}")
                content = xml_file.read()
            log_debug(f"Thread {thread_id}: Successfully extracted {len(content)} bytes from {internal_path}")
            return content
        except zipfile.BadZipFile as e:
            log_error(f"Thread {thread_id}: Bad ZIP file error extracting {internal_path} from {zip_path}: {e}")
            raise
        except KeyError as e:
            log_error(f"Thread {thread_id}: File not found in ZIP extracting {internal_path} from {zip_path}: {e}")
            raise
        except Exception as e:
            log_error(f"Thread {thread_id}: Unexpected error extracting {internal_path} from {zip_path}: {e}")
            raise

    @classmethod
    def cleanup_zip_cache(cls):
        """Clean up cached ZIP connections with reference counting"""
        with cls._zip_cache_lock:
            print(f"Cleaning up {len(cls._zip_cache)} cached ZIP connections")
            for zip_path, zip_ref in cls._zip_cache.items():
                try:
                    print(f"Closing ZIP connection for {zip_path} (ref_count was: {cls._zip_cache_ref_count.get(zip_path, 0)})")
                    zip_ref.close()
                except Exception as e:
                    print(f"Error closing ZIP connection for {zip_path}: {e}")
            cls._zip_cache.clear()
            cls._zip_cache_ref_count.clear()
            print("Cleaned up XML processor ZIP file cache")
