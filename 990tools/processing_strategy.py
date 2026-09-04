#!/usr/bin/env python3
"""
processing_strategy.py - High-level coordination for IRS 990 processing phases

This module provides high-level coordination between different processing phases
of the IRS 990 pipeline. Each processor now handles its own threading and
producer-consumer patterns internally.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import logging

from database_operations import DatabaseOperations
from logging_utils import get_logger, log_info, log_error
from config import global_config


class ProcessingCoordinator:
    """High-level coordinator for IRS 990 processing phases"""

    def __init__(self, db_ops: DatabaseOperations):
        self.db_ops = db_ops
        self.logger = get_logger("processing_coordinator")

    def run_processing_pipeline(self, start_step: str = "xml", stop_step: str = "geocode",
                               max_files: Optional[int] = None, workers: int = 4) -> Dict[str, Any]:
        """
        Run the complete IRS 990 processing pipeline from start_step to stop_step.

        Args:
            start_step: Step to start processing from ("irsfetch", "zip", "xml", "address", "geocode")
            stop_step: Step to stop processing at
            max_files: Maximum files to process (for testing)
            workers: Number of worker threads

        Returns:
            Dictionary with results from each processing step
        """
        results = {}
        steps = ["irsfetch", "zip", "xml", "address", "geocode"]

        # Validate steps
        if start_step not in steps or stop_step not in steps:
            raise ValueError(f"Invalid step. Must be one of: {steps}")

        start_idx = steps.index(start_step)
        stop_idx = steps.index(stop_step)

        if start_idx > stop_idx:
            raise ValueError("start_step must come before stop_step in pipeline")

        # Run each step in sequence
        for i in range(start_idx, stop_idx + 1):
            step = steps[i]
            self.log_info(f"Starting processing step: {step}")

            try:
                if step == "irsfetch":
                    results[step] = self._run_irsfetch(max_files)
                elif step == "zip":
                    results[step] = self._run_zip_processing(max_files)
                elif step == "xml":
                    results[step] = self._run_xml_processing(max_files, workers)
                elif step == "address":
                    results[step] = self._run_address_deduplication(max_files)
                elif step == "geocode":
                    results[step] = self._run_geocoding(max_files)

                self.log_info(f"Completed processing step: {step} - {results[step]} items processed")

            except Exception as e:
                self.log_error(f"Failed processing step {step}: {e}", exc_info=True)
                raise

        return results

    def _run_irsfetch(self, max_files: Optional[int]) -> int:
        """Run IRS fetch processing"""
        from irsfetch_processor import IRSFetchProcessor
        processor = IRSFetchProcessor()
        # For now, hardcode years - this could be made configurable
        return processor.fetch_irs_zips(2020, 2023)  # Example range

    def _run_zip_processing(self, max_files: Optional[int]) -> int:
        """Run ZIP file processing"""
        from zip_processor import ZipProcessor
        processor = ZipProcessor(self.db_ops, "/Volumes/Data/irs_zips")
        return processor.process_zip_files(2020, 2023)  # Example range

    def _run_xml_processing(self, max_files: Optional[int], workers: int) -> int:
        """Run XML file processing"""
        from xml_processor import XMLProcessor
        processor = XMLProcessor(self.db_ops)
        return processor.process_xml_files(max_files, workers)

    def _run_address_deduplication(self, max_files: Optional[int]) -> int:
        """Run address deduplication processing"""
        from address_deduplication_processor import AddressDeduplicationProcessor
        processor = AddressDeduplicationProcessor(self.db_ops)
        return processor.deduplicate_addresses()

    def _run_geocoding(self, max_files: Optional[int]) -> int:
        """Run geocoding processing"""
        from geocoding_api_processor import GeocodingAPIProcessor
        processor = GeocodingAPIProcessor(self.db_ops)
        return processor.process_pending_geocoding_records()

    def log_info(self, msg: str, *args, **kwargs):
        """Log info message"""
        if not global_config.is_quiet():
            log_info(self.logger, msg, *args, **kwargs)

    def log_error(self, msg: str, *args, exc_info: bool = False, **kwargs):
        """Log error message"""
        log_error(self.logger, msg, *args, exc_info=exc_info, **kwargs)


