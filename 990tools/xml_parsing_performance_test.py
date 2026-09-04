#!/usr/bin/env python3
"""
xml_parsing_performance_test.py - Performance test fixture for XML parsing

This script tests XML parsing performance by repeatedly parsing all XML files
in ./test_xmls/*990*.xml using the existing parsing infrastructure. It integrates
cProfile for detailed performance analysis and logs object counts and operations
without actually saving to the database.

Usage:
    python xml_parsing_performance_test.py --iterations 10

Arguments:
    --iterations: Number of times to iterate through all XML files (default: 1)
    --profile: Enable cProfile profiling (default: False)
    --quiet: Suppress detailed logging (default: False)
"""

import argparse
import cProfile
import glob
import os
import pstats
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Add the current directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pending_database_context import PendingDatabaseContext
from xml_processor import XMLProcessor
from database_operations import DatabaseOperations
from logging_utils import log_info, log_error, log_debug, log_warning
from config import global_config
from constants import CURRENT_PROCESSING_VERSION


class XMLParsingPerformanceTest:
    """
    Performance test fixture for XML parsing.

    This class handles the discovery, parsing, and profiling of XML files
    using the existing XML processing infrastructure.
    """

    def __init__(self, iterations: int = 1, profile: bool = False, quiet: bool = False, form_types: List[str] = None):
        """
        Initialize the performance test.

        Args:
            iterations: Number of times to iterate through all XML files
            profile: Whether to enable cProfile profiling
            quiet: Whether to suppress detailed logging
            form_types: List of form types to test (["all"] means all forms)
        """
        self.iterations = iterations
        self.profile = profile
        self.quiet = quiet
        self.form_types = form_types or ["all"]

        # Set global config for quiet mode
        if quiet:
            global_config._quiet = True

        # Initialize database operations (but we'll mock the database)
        # Use a dummy database path to avoid initialization issues
        self.db_ops = None  # We'll mock all database operations

        # Initialize XML processor with None db_ops (we'll override methods)
        self.xml_processor = XMLProcessor(None, CURRENT_PROCESSING_VERSION)

        # Track performance metrics
        self.total_files_processed = 0
        self.total_parsing_time = 0.0
        self.total_objects_created = 0
        self.total_operations_created = 0

    def discover_xml_files(self) -> List[Path]:
        """
        Discover XML files matching the specified form types in test_xmls directory.

        Returns:
            List of Path objects for XML files to process
        """
        test_xmls_dir = Path(__file__).parent / "test_xmls"

        # Determine which patterns to use based on form_types
        if "all" in self.form_types:
            patterns = ["*990*.xml"]
        else:
            patterns = []
            if "990" in self.form_types:
                patterns.append("*990*.xml")
            if "990ez" in self.form_types:
                patterns.append("*990EZ*.xml")
            if "990pf" in self.form_types:
                patterns.append("*990PF*.xml")

        xml_files = []
        for pattern in patterns:
            xml_files.extend(list(test_xmls_dir.glob(pattern)))

        # Remove duplicates and sort
        xml_files = sorted(list(set(xml_files)))

        if not xml_files:
            form_type_str = ", ".join(self.form_types)
            log_error(f"No XML files found for form types '{form_type_str}' in {test_xmls_dir}")
            return []

        log_info(f"Found {len(xml_files)} XML files to process (form types: {', '.join(self.form_types)}):")
        for xml_file in xml_files:
            log_info(f"  - {xml_file.name}")

        return xml_files

    def parse_single_xml_file(self, xml_file: Path) -> Tuple[bool, PendingDatabaseContext, float]:
        """
        Parse a single XML file and return the context and timing.

        Args:
            xml_file: Path to the XML file to parse

        Returns:
            Tuple of (success: bool, context: PendingDatabaseContext, parse_time: float)
        """
        start_time = time.time()

        try:
            # Read XML content
            with open(xml_file, 'rb') as f:
                xml_content = f.read()

            # Create a mock XML file record for processing
            # Since we're not using a real database, we'll create minimal mock data
            xml_id = f"test_{xml_file.stem}"
            zip_id = "test_zip"
            filename = xml_file.name
            internal_path = xml_file.name
            file_size = len(xml_content)

            # Mock the database operations that the XML producer expects
            # Instead of querying the database, we'll directly call the parsing logic
            # by bypassing the database-dependent parts

            # Create context for this XML file processing
            context = PendingDatabaseContext(xml_id=xml_id)

            # Parse the XML directly using the producer's internal method
            # We'll mock the zip file path lookup
            success = self._parse_xml_with_mocked_db(xml_file, xml_content, context)

            parse_time = time.time() - start_time

            if success:
                if not self.quiet:
                    log_debug(f"SUCCESS: Parsed {filename} in {parse_time:.3f}s")
            else:
                log_warning(f"FAILED: Parsing {filename} failed (error: {context.error_message})")

            return success, context, parse_time

        except Exception as e:
            parse_time = time.time() - start_time
            log_error(f"EXCEPTION: Failed to parse {xml_file.name}: {e}")
            # Return empty context on failure
            return False, PendingDatabaseContext(), parse_time

    def _parse_xml_with_mocked_db(self, xml_file: Path, xml_content: bytes, context: PendingDatabaseContext, cached_charity=None) -> bool:
        """
        Parse XML content with mocked database operations.

        Args:
            xml_file: Path to the XML file
            xml_content: Raw XML content
            context: PendingDatabaseContext to collect objects

        Returns:
            bool: Success status
        """
        try:
            from lxml import etree
            from io import BytesIO

            # Parse XML
            parser = etree.XMLParser(recover=True)
            tree = etree.parse(BytesIO(xml_content), parser)
            root = tree.getroot()

            # Extract basic metadata
            form_type = self._extract_form_type_mock(root)
            tax_year = self._extract_tax_year_mock(root)
            filer_ein = self._extract_filer_ein_mock(root)

            if not filer_ein or filer_ein == "Unknown":
                if not self.quiet:
                    log_error(f"Skipping XML {xml_file.name}: invalid EIN {filer_ein}")
                return False

            # Create charity object first
            from models import Charity
            charity = Charity(
                ein=filer_ein,
                tax_year=tax_year,
                form_type=form_type,
                xml_name=xml_file.name
            )
            # Force ID generation before adding to context and parsing dependents
            charity.prep_for_insert()
            if not self.quiet:
                log_info(f"CREATING CHARITY: EIN {filer_ein}, tax_year {tax_year}, form_type {form_type}, xml_name {xml_file.name}")
            context.addObjectToDatabase(charity)

            # CACHE the charity object to avoid repeated context.getCharity() calls
            cached_charity = charity

            # Use base parser factory to get the correct parser and parse the form
            from base_parser import BaseParser
            parser = BaseParser.create_parser(form_type)
            if parser:
                # Pass the cached charity to avoid repeated lookups
                parser.parse_form(root, xml_file.name, {}, context, cached_charity=cached_charity)
            else:
                if not self.quiet:
                    log_info(f"Unsupported form type {form_type} in {xml_file.name}")
                return False

            # Explicit cleanup after parsing
            del root, tree

            # Log grant collection results
            counts = context.getObjectCounts()
            if not self.quiet:
                log_info(f"PROCESSING COMPLETE: EIN {filer_ein} in {xml_file.name}: {counts['grant']} grants, {counts['contractor']} contractors, {counts['political_contribution']} contributions, {counts['officer']} officers, {counts['address']} addresses",
                          ein=filer_ein)

            if not self.quiet:
                log_debug(f"SUCCESS: Parsed {xml_file.name}: charity={filer_ein}, grants={counts['grant']}, officers={counts['officer']}, contractors={counts['contractor']}, contributions={counts['political_contribution']}, addresses={counts['address']}")
            return True

        except Exception as e:
            import traceback
            error_msg = f"Unexpected Error: {str(e)}\n\nStack Trace:\n{traceback.format_exc()}"
            context.error_message = error_msg
            return False

    def _extract_form_type_mock(self, root) -> str:
        """Extract form type from XML with validation (mocked version)"""
        from xpaths import COMMON_XPATHS
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
                        return "Unknown"
            except:
                continue
        return "Unknown"

    def _extract_tax_year_mock(self, root) -> int:
        """Extract tax year from XML (mocked version)"""
        from xpaths import COMMON_XPATHS
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

    def _extract_filer_ein_mock(self, root) -> str:
        """Extract filer EIN from XML (mocked version)"""
        from xpaths import COMMON_XPATHS
        for xpath in COMMON_XPATHS["filer_ein"]:
            try:
                result = xpath(root)
                if result:
                    raw_ein = result[0].text.strip()
                    if raw_ein.isdigit():
                        formatted_ein = f"{int(raw_ein):09d}"
                        return formatted_ein
                    else:
                        raise ValueError(f"Invalid EIN format: '{raw_ein}' - must be numeric")
            except Exception as e:
                if not self.quiet:
                    log_debug(f"XPath {xpath.path} failed: {e}")
                continue
        raise ValueError("No EIN found in XML")

    def log_context_summary(self, context: PendingDatabaseContext, iteration: int, file_index: int, total_files: int, filename: str):
        """
        Log a summary of objects and operations in the context.

        Args:
            context: The PendingDatabaseContext to summarize
            iteration: Current iteration number
            file_index: Index of current file in iteration
            total_files: Total number of files in iteration
            filename: Name of the XML file
        """
        object_counts = context.getObjectCounts()
        operations_count = len(context.operations)

        # Update totals
        self.total_objects_created += sum(object_counts.values())
        self.total_operations_created += operations_count

        if not self.quiet:
            log_info(f"[{iteration+1}/{self.iterations}] [{file_index+1}/{total_files}] {filename}:")
            log_info(f"  Objects: {object_counts}")
            log_info(f"  Operations: {operations_count}")
            if context.error_message:
                log_info(f"  Error: {context.error_message}")

    def run_performance_test(self) -> Dict[str, Any]:
        """
        Run the complete performance test.

        Returns:
            Dictionary with performance metrics
        """
        log_info(f"Starting XML parsing performance test")
        log_info(f"  Iterations: {self.iterations}")
        log_info(f"  Profiling: {'Enabled' if self.profile else 'Disabled'}")
        log_info(f"  Quiet mode: {'Enabled' if self.quiet else 'Disabled'}")

        # Discover XML files
        xml_files = self.discover_xml_files()
        if not xml_files:
            return {"error": "No XML files found"}

        total_files = len(xml_files)
        log_info(f"Processing {total_files} XML files per iteration")

        # Collect name parsing statistics
        name_stats = {
            'simple_names': 0,
            'complex_names': 0,
            'total_names': 0,
            'name_lengths': [],
            'name_patterns': {}
        }

        # Run the test iterations
        overall_start_time = time.time()

        for iteration in range(self.iterations):
            iteration_start_time = time.time()
            log_info(f"\n=== Iteration {iteration + 1}/{self.iterations} ===")

            for file_index, xml_file in enumerate(xml_files):
                # Parse the XML file
                success, context, parse_time = self.parse_single_xml_file(xml_file)

                # Update timing
                self.total_parsing_time += parse_time
                self.total_files_processed += 1

                # Log context summary
                self.log_context_summary(context, iteration, file_index, total_files, xml_file.name)

                # Collect name statistics from this context
                self._collect_name_stats(context, name_stats)

                # Clean up context to free memory
                context.clear()
                del context

        overall_time = time.time() - overall_start_time

        # Calculate final metrics
        metrics = {
            "total_iterations": self.iterations,
            "total_files_per_iteration": total_files,
            "total_files_processed": self.total_files_processed,
            "total_parsing_time_seconds": self.total_parsing_time,
            "overall_time_seconds": overall_time,
            "average_parse_time_per_file": self.total_parsing_time / self.total_files_processed if self.total_files_processed > 0 else 0,
            "average_parse_time_per_iteration": self.total_parsing_time / self.iterations if self.iterations > 0 else 0,
            "total_objects_created": self.total_objects_created,
            "total_operations_created": self.total_operations_created,
            "objects_per_second": self.total_objects_created / overall_time if overall_time > 0 else 0,
            "files_per_second": self.total_files_processed / overall_time if overall_time > 0 else 0,
            "name_parsing_stats": name_stats
        }

        # Log final summary
        log_info("\n=== PERFORMANCE TEST COMPLETE ===")
        log_info(f"Total iterations: {metrics['total_iterations']}")
        log_info(f"Files processed: {metrics['total_files_processed']} ({metrics['total_files_per_iteration']} per iteration)")
        log_info(f"Total parsing time: {metrics['total_parsing_time_seconds']:.3f}s")
        log_info(f"Overall time: {metrics['overall_time_seconds']:.3f}s")
        log_info(f"Average parse time per file: {metrics['average_parse_time_per_file']:.3f}s")
        log_info(f"Average parse time per iteration: {metrics['average_parse_time_per_iteration']:.3f}s")
        log_info(f"Total objects created: {metrics['total_objects_created']}")
        log_info(f"Total operations created: {metrics['total_operations_created']}")
        log_info(f"Objects per second: {metrics['objects_per_second']:.1f}")
        log_info(f"Files per second: {metrics['files_per_second']:.2f}")

        # Log name parsing statistics
        log_info("\n=== NAME PARSING STATISTICS ===")
        log_info(f"Total names parsed: {name_stats['total_names']}")
        if name_stats['total_names'] > 0:
            log_info(f"Simple names (≤2 parts): {name_stats['simple_names']} ({name_stats['simple_names']/name_stats['total_names']*100:.1f}%)")
            log_info(f"Complex names (>2 parts): {name_stats['complex_names']} ({name_stats['complex_names']/name_stats['total_names']*100:.1f}%)")
        if name_stats['name_lengths']:
            avg_length = sum(name_stats['name_lengths']) / len(name_stats['name_lengths'])
            log_info(f"Average name length: {avg_length:.1f} characters")
        log_info("Top name patterns:")
        sorted_patterns = sorted(name_stats['name_patterns'].items(), key=lambda x: x[1], reverse=True)[:10]
        for pattern, count in sorted_patterns:
            log_info(f"  '{pattern}': {count} times")

        return metrics

    def _collect_name_stats(self, context, name_stats):
        """Collect statistics about name parsing patterns"""
        officers = context.getObjectsByType('officer')
        for officer in officers:
            if hasattr(officer, 'full_name') and officer.full_name:
                name = officer.full_name.strip()
                if name:
                    name_stats['total_names'] += 1
                    name_stats['name_lengths'].append(len(name))

                    # Categorize name complexity
                    parts = [p for p in name.split() if p]
                    if len(parts) <= 2:
                        name_stats['simple_names'] += 1
                        pattern = f"{len(parts)}-part"
                    else:
                        name_stats['complex_names'] += 1
                        pattern = f"{len(parts)}-part"

                    # Track patterns
                    if pattern not in name_stats['name_patterns']:
                        name_stats['name_patterns'][pattern] = 0
                    name_stats['name_patterns'][pattern] += 1


def main():
    """Main entry point for the performance test."""
    parser = argparse.ArgumentParser(description="XML Parsing Performance Test Fixture")
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of times to iterate through all XML files (default: 1)"
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Enable cProfile profiling"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress detailed logging"
    )
    parser.add_argument(
        "--form-types",
        nargs="+",
        choices=["all", "990", "990ez", "990pf"],
        default=["all"],
        help="Form types to test (default: all)"
    )

    args = parser.parse_args()

    # Create and run the performance test
    test = XMLParsingPerformanceTest(
        iterations=args.iterations,
        profile=args.profile,
        quiet=args.quiet,
        form_types=args.form_types
    )

    if args.profile:
        # Run with profiling
        profiler = cProfile.Profile()
        profiler.enable()

        try:
            metrics = test.run_performance_test()
        finally:
            profiler.disable()

            # Print profiling results
            stats = pstats.Stats(profiler)
            stats.sort_stats('cumulative')
            print("\n=== PROFILING RESULTS ===")
            stats.print_stats(20)  # Top 20 functions

    else:
        # Run without profiling
        metrics = test.run_performance_test()

    # Exit with success
    sys.exit(0)


if __name__ == "__main__":
    main()