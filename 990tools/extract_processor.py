#!/usr/bin/env python3
"""
extract_processor.py - XML file extraction by EIN

This module handles extracting XML files for specific EINs from ZIP archives
to a specified destination directory.
"""

import os
import zipfile
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from logging_utils import log_info, log_error, log_debug, log_warning
from config import global_config
from base_processor import BaseProducer
from queue_status_display import QueueStatusDisplay


class ExtractProcessor(BaseProducer):
    """Handles XML file extraction by EIN"""
 
    def __init__(self, db_ops, zips_dir: str):
        batch_size = getattr(global_config, 'batch_size', 100)
        super().__init__(db_ops, batch_size)
        self.zips_dir = zips_dir
        self.extracted_files = 0

        # Initialize QueueStatusDisplay for visual monitoring (will be started by extract_xml_files)
        self.queue_status_display = None

    def _get_custom_metrics(self) -> Dict[str, Any]:
        """Custom metrics for extract processor."""
        return {'extracted_files': self.extracted_files}

    def _get_work_batch(self, last_pk: Optional[str] = None) -> Tuple[List[Tuple[str, str, str, str, int]], Optional[str]]:
        """Get a batch of XML extraction work items using key-value paging on xml_id"""
        if self.shutdown_event.is_set() or self.exit_processing:
            return [], None
        if not hasattr(self, 'eins') or not self.eins:
            return [], None
 
        placeholders = ','.join(['?'] * len(self.eins))
        params = self.eins[:]
        if last_pk is not None:
            params.append(last_pk)
        params.append(self.batch_size)
 
        where = f"xf.ein IN ({placeholders})"
        if last_pk is not None:
            where += " AND xf.xml_id > ?"
 
        query = f"""
            SELECT xf.ein, xf.filename, zf.file_path, xf.internal_path, xf.tax_year, xf.xml_id
            FROM XmlFiles xf
            JOIN ZipFiles zf ON xf.zip_id = zf.zip_id
            WHERE {where}
            ORDER BY xf.xml_id
            LIMIT ?
        """
        rows = self.db_ops.execute_query(query, params).fetchall()
 
        if not rows:
            return [], None
 
        max_pk = max(row[5] for row in rows)
        batch = [(row[0], row[1], row[2], row[3], row[4]) for row in rows]
        return batch, max_pk

    def extract_xml_files(self, eins: List[str], dest_dir: str) -> int:
        """Extract XML files for specified EINs to destination directory using key-value paging"""
        log_info(f"Extracting XML files for {len(eins)} EINs to {dest_dir}")
 
        # Create destination directory
        os.makedirs(dest_dir, exist_ok=True)
 
        self.eins = eins
        self.setup_status_gauges(interval=10.0)

        # Initialize and start QueueStatusDisplay for visual monitoring
        # Note: ExtractProcessor doesn't use a result queue, so we'll create a simple queue for monitoring
        import queue
        monitoring_queue = queue.Queue()
        self.queue_status_display = QueueStatusDisplay(monitoring_queue, update_interval=30.0)
        self.queue_status_display.start()

        extracted_count = 0
        last_pk = None
        while True:
            if self.exit_processing:
                log_info("Shutdown requested during XML extraction")
                break
            xml_infos, last_pk = self._get_work_batch(last_pk)
            if not xml_infos:
                break
 
            log_debug(f"Processing batch of {len(xml_infos)} XML files")
 
            for row in xml_infos:
                if self.exit_processing:
                    log_info("Shutdown requested during XML extraction")
                    break
                ein, filename, zip_path, internal_path, tax_year = row
                xml_info = (filename, zip_path, internal_path, tax_year)
                if self._extract_single_xml_with_custom_name(xml_info, dest_dir, ein):
                    extracted_count += 1
                    self.extracted_files += 1
 
        log_info(f"Extraction complete. Extracted {extracted_count} XML files.")

        # Stop QueueStatusDisplay
        if self.queue_status_display:
            self.queue_status_display.stop()

        return extracted_count


    def _extract_single_xml_with_custom_name(self, xml_info: tuple, dest_dir: str, ein: str) -> bool:
        """Extract a single XML file with custom naming: <ein>_<tax_year>.xml"""
        filename, zip_path, internal_path, tax_year = xml_info

        try:
            # Create custom filename
            custom_filename = f"{ein}_{tax_year}.xml"
            dest_path = os.path.join(dest_dir, custom_filename)

            # Open ZIP file
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Extract to temporary location first
                temp_path = dest_path + '.tmp'
                with zip_ref.open(internal_path) as source, open(temp_path, 'wb') as target:
                    shutil.copyfileobj(source, target)

                # Move to final location
                os.rename(temp_path, dest_path)

                log_debug(f"Extracted {filename} as {custom_filename} to {dest_path}")
                return True

        except Exception as e:
            log_error(f"Failed to extract {filename}: {e}")
            # Clean up temp file if it exists
            temp_path = os.path.join(dest_dir, f"{ein}_{tax_year}.xml") + '.tmp'
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            return False