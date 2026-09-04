#!/usr/bin/env python3
"""
990processor.py - Comprehensive IRS 990 data processing module

This module replaces the collection of separate scripts with a unified,
database-driven processing pipeline for IRS Form 990 data.

Key Features:
- Dataclass-based data models for type safety and clarity
- DuckDB database storage with proper relationships
- Geolocation using censusgeocode API
- Comprehensive error handling and logging
- Threaded processing for performance
"""


import os
import sys
import argparse
import time
import zipfile
import threading
import cProfile
import pstats
import io
import signal
import faulthandler
from constants import MONITOR_INTERVAL_SECONDS
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
from queue import Queue
from io import BytesIO
# etree import removed - use xpath_utils or xpaths.py for XPath operations

try:
    import censusgeocode as cg
except ImportError:
    cg = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# Import extracted modules
from database_operations import DatabaseOperations
from xml_processor import XMLProcessor
from bmf_processor import BmfProcessor
from geocoding_api_processor import GeocodingAPIProcessor
from zip_processor import ZipProcessor
from percentile_calculator import PercentileCalculator
from export_processor import TSVExporter
from address_matcher import AddressMatcher
from address_deduplication_processor import AddressDeduplicationProcessor  # type: ignore
from irsfetch_processor import IRSFetchProcessor
from officer_deduplication_processor import OfficerDeduplicationProcessor
from photo_processor import PhotoProcessor
from extract_processor import ExtractProcessor
from grant_match_processor import GrantMatchProcessor
from backfill_charities_processor import BackfillCharitiesProcessor
from geolocate_prev_processor import GeolocatePrevProcessor
from geolocate_archive_processor import GeolocateArchiveProcessor
from einless_processor import EinlessProcessor
from fec_processor import FECProcessor
from medicare_processor import MedicareProcessor
from sanctions_processor import SanctionsProcessor
from dot_processor import DotProcessor
from logging_utils import log_info, log_error, log_debug, log_warning, update_logging_config
from config import global_config
from queue_status_display import QueueStatusDisplay


def _parse_cycle_list(raw: str) -> Optional[List[int]]:
    """Parse FEC_CYCLES env (e.g. '2024' or '2020,2022,2024'); empty → all default cycles."""
    raw = (raw or "").strip()
    if not raw:
        return None
    cycles: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            cycles.append(int(part))
    return cycles or None


# Parsing functions are now handled by base_parser factory method

# Import dataclasses
from models import Charity, Officer, Grant, Contractor, PoliticalContribution
from base_processor import BaseProcessor

# Constants
DEFAULT_DB_PATH = "irs990.duckdb"
DEFAULT_ZIPS_DIR = "/Volumes/Data/irs_zips"
DEFAULT_OUT_DIR = "/Volumes/Data/tsvs"
DEFAULT_ANAL_DIR = "/Volumes/Data/atsvs"
DEFAULT_FINAL_DIR = "/Volumes/Data/final"

# Processing version constants
CURRENT_PROCESSING_VERSION = 2  # Increment when processing logic changes (refactored)

# Threading constants
MAX_WORKERS = 16
QUEUE_SIZE = 1000
BATCH_SIZE = 100

# Geolocate (after match): prev → census bulk → API tail → grok batch → archive.
# geolocate_new = legacy combined census+api (one step); prefer census then api separately.
PIPELINE_STEPS = [
    "irsfetch", "zip", "bmf", "xml", "fec", "medicare", "sanctions", "dot", "address", "einless", "match",
    "geolocate_prev", "geolocate_census", "geolocate_api", "geolocate_new", "geolocate_grok",
    "geolocate_archive",
    "grant_match", "backfill", "photos", "ratios",
    "percentiles", "export",
]
STEP_ALIASES = {
    "geolocate": "geolocate_new",
    "geolocate1": "geolocate_prev",
}


def normalize_step(step: str) -> str:
    return STEP_ALIASES.get(step, step)



class IRS990Processor(BaseProcessor):
    """Main processor class for IRS 990 data"""
  
    def __init__(self, db_path: str = DEFAULT_DB_PATH, zips_dir: str = DEFAULT_ZIPS_DIR,
                 out_dir: str = DEFAULT_OUT_DIR, anal_dir: str = DEFAULT_ANAL_DIR,
                 final_dir: str = DEFAULT_FINAL_DIR, verbose: bool = False, quiet: bool = False, max_files: Optional[int] = None, log_sql: bool = False, workers: int = MAX_WORKERS, dbUI: bool = False, profile_seconds: Optional[int] = None, progress: str = "files", extract: Optional[List[str]] = None, extract_dest: Optional[str] = None, nostats: bool = False, no_backpressure: bool = False, collect_xpath_stats: bool = False):
        # Set global config from parameters (for backward compatibility)
        global_config.db_path = db_path if db_path != DEFAULT_DB_PATH else os.path.join(final_dir, "irs990.duckdb")
        global_config.final_dir = final_dir
        global_config.zips_dir = zips_dir
        global_config.out_dir = out_dir
        global_config.anal_dir = anal_dir
        global_config.final_dir = final_dir
        global_config.verbose = verbose
        global_config.quiet = quiet
        global_config.max_files = max_files
        global_config.log_sql = log_sql
        global_config.workers = workers
        global_config.dbUI = dbUI
        global_config.profile_seconds = profile_seconds
        global_config.progress = progress
        global_config.extract = extract
        global_config.extract_dest = extract_dest
        global_config.nostats = nostats
        global_config.no_backpressure = no_backpressure
        global_config.collect_xpath_stats = collect_xpath_stats
  
        # Determine database path
        if db_path == DEFAULT_DB_PATH:
            db_path = os.path.join(final_dir, "irs990.duckdb")
        self.db_path = db_path
        self.final_dir = final_dir  # Store final_dir for later use
        self.zips_dir = zips_dir
        self.out_dir = out_dir
        self.anal_dir = anal_dir
        self.final_dir = final_dir
        self.verbose = verbose
        self.quiet = quiet
        self.max_files = max_files
        self.log_sql = log_sql
        self.processed_steps = 0
  
        # Setup logging
        # Log that signal handler is active (USR1 handler is set up in base_processor.py)
        log_info("USR1 signal handler available for stack trace dumps (via base_processor.py)")
  
        # Initialize components
        DatabaseOperations._pool = DatabaseOperations.bootstrap(self.db_path, dbUI=global_config.dbUI)
        self.db_ops = DatabaseOperations(self.db_path, dbUI=global_config.dbUI)
        super().__init__(self.db_ops)
        self.zip_processor = ZipProcessor(self.db_ops, global_config.zips_dir)
        self.xml_processor = XMLProcessor(self.db_ops)
        self.bmf_processor = BmfProcessor(self.db_ops)
        self.geolocation_processor = None # GeocodingAPIProcessor(self.db_ops)
        self.address_matcher = AddressMatcher(self.db_ops)
        self.percentile_calculator = PercentileCalculator(self.db_ops)
        # Initialize TSV exporter
        self.tsv_exporter = TSVExporter(self.db_ops, global_config.final_dir)
        # Initialize IRS fetch processor
        self.irs_fetch_processor = IRSFetchProcessor(global_config.zips_dir)
        # Initialize photo processor
        self.photo_processor = PhotoProcessor(self.db_ops)
        # Initialize extract processor
        self.extract_processor = ExtractProcessor(self.db_ops, global_config.zips_dir)
        # Initialize address deduplication processor
        self.address_dedup_processor = AddressDeduplicationProcessor(self.db_ops)
        # Initialize officer deduplication processor
        self.officer_dedup_processor = OfficerDeduplicationProcessor(self.db_ops)
        # Initialize grant match processor
        self.grant_match_processor = GrantMatchProcessor(self.db_ops)
        # Initialize backfill charities processor
        self.backfill_charities_processor = BackfillCharitiesProcessor(self.db_ops)
        # Phonebook exact-core resolution for no-EIN grantees (before match/geolocate).
        # TSV exports land in 990tools root for offline einless/rebuild tooling.
        einless_tsv_dir = Path(__file__).resolve().parent
        self.einless_processor = EinlessProcessor(self.db_ops, output_dir=einless_tsv_dir)
        self.geolocate_prev_processor = GeolocatePrevProcessor(self.db_ops)
        self.geolocate_archive_processor = GeolocateArchiveProcessor(self.db_ops)
        cms_data_dir = Path(self.final_dir) / "cms_data"
        fec_cycles = _parse_cycle_list(os.environ.get("FEC_CYCLES", ""))
        self.fec_processor = FECProcessor(
            self.db_ops,
            data_dir=cms_data_dir / "fec",
            cycles=fec_cycles,
        )
        self.medicare_processor = MedicareProcessor(self.db_ops, data_dir=cms_data_dir / "medicare")
        self.sanctions_processor = SanctionsProcessor(
            self.db_ops, data_dir=cms_data_dir / "treasury"
        )
        self.dot_processor = DotProcessor(self.db_ops, data_dir=cms_data_dir / "dot")
        # Initialize bulk operations
        self.bulk_ops = self.db_ops.get_bulk_operations()

        # Initialize stats processor
        self.stats_processor = self.db_ops.get_stats_processor()
  
        # Initialize database
        #self._init_database()
  
        # Initialize instance variables
        self.zips_dir = zips_dir
        self.out_dir = out_dir
        self.anal_dir = anal_dir
        self.final_dir = final_dir
        self.verbose = verbose
        self.quiet = quiet
        self.max_files = max_files
        self.log_sql = log_sql
        self.dbUI = dbUI
        self.workers = workers
        self.profile_seconds = profile_seconds
        self.progress = progress
        self.extract = extract
        self.extract_dest = extract_dest
        self.nostats = nostats
        self.collect_xpath_stats = collect_xpath_stats

    def _get_custom_metrics(self) -> Dict[str, Any]:
        """Custom metrics for IRS990 processor."""
        return {'processed_steps': self.processed_steps}

    def _init_database(self):
        """Initialize DuckDB database with schema"""
        # The database is already initialized by DatabaseOperations
        if not os.path.isabs(self.db_path):
            self.db_path = os.path.join(self.final_dir, self.db_path)
        

    def get_os_thread_name(tid):
        try:
            with open(f"/proc/{os.getpid()}/task/{tid}/comm") as f:
                return f.read().strip()
        except:
            return "unknown"
        
    def _dump_stack_traces(self, signum, frame):
        """Dump stack traces of all threads when USR1 signal is received"""
        import traceback
        import sys

        print("\n"*5,"\n=== STACK TRACE DUMP (USR1 signal received) ===", file=sys.stderr)
        print(f"Timestamp: {datetime.now().isoformat()}", file=sys.stderr)

        # Get all threads
        threads = threading.enumerate()

        for i, thread in enumerate(threads, 1):
            # Use thread.name directly — this is what you assigned
            name = thread.name if thread.name else f"Unnamed-{thread.ident}"
            os_name = self.get_os_thread_name(thread.ident)
            status = "alive" if thread.is_alive() else "dead"
            daemon = "daemon" if thread.daemon else "non-daemon"            
            print(f"Thread {i}: {os_name}/{name} (ident: {thread.ident}, daemon: {daemon})", file=sys.stderr)
            if thread.is_alive():
                try:
                    thread_id = thread.ident
                    if thread_id in sys._current_frames():
                        frame = sys._current_frames()[thread_id]
                        print(f"  Stack trace for {name}:", file=sys.stderr)
                        traceback.print_stack(frame, file=sys.stderr)
                    else:
                        print(f"  (No stack frame available for {name})", file=sys.stderr)
                except Exception as e:
                    print(f"  (Failed to get stack for {name}: {e})", file=sys.stderr)
            else:
                print(f"  ({name} is not alive)", file=sys.stderr)
            
            print("-" * 60, file=sys.stderr)

        print(f"\n=== END STACK TRACE DUMP === {'\n'*5}", file=sys.stderr)
        sys.stderr.flush()

        """Recompress ZIP files to standard format using 7z and zip"""
        import glob
        import shutil
        import subprocess

        def check_tools():
            """Check if required tools (7z, zip) are available."""
            for tool in ["7z", "zip"]:
                if shutil.which(tool) is None:
                    raise RuntimeError(f"Error: {tool} is not installed. Install with 'brew install {tool}'.")

        def check_compression(zip_file):
            """Check if ZIP file uses unsupported compression methods."""
            try:
                with zipfile.ZipFile(zip_file, "r") as zf:
                    for file_info in zf.infolist():
                        if file_info.compress_type not in (0, 8):  # ZIP_STORED=0, ZIP_DEFLATED=8
                            return True, f"Unsupported compression type {file_info.compress_type} in {file_info.filename}"
                return False, "All files use supported compression (Stored or Deflated)"
            except zipfile.BadZipFile as e:
                return True, f"Malformed ZIP file: {e}"
            except Exception as e:
                return True, f"Error reading ZIP: {e}"

        def recompress_zip(zip_file):
            """Recompress a single ZIP file using Deflate."""
            base_name = os.path.basename(zip_file)
            log_info(f"Recompressing {zip_file}...")
            log_debug(f"Current working directory: {os.getcwd()}")

            # Clean temp directory
            temp_dir = os.path.join(self.zips_dir, "temp")
            if os.path.exists(temp_dir):
                for item in Path(temp_dir).glob("*"):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)

            # Create temp directory
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = temp_dir
            log_debug(f"Using temp directory: {temp_path}")

            # Extract with 7z
            try:
                subprocess.run(
                    ["7z", "x", zip_file, f"-o{temp_path}", "-y"],
                    check=True,
                    capture_output=True,
                    text=True
                )
            except subprocess.CalledProcessError as e:
                error_msg = f"Error extracting {zip_file}: {e.stderr}"
                log_error(error_msg)
                return False

            # Count extracted files
            extracted_files = len(list(Path(temp_path).rglob("*.xml")))
            log_info(f"Extracted {extracted_files} files from {zip_file}.")

            # Recompress with zip in one go
            temp_zip = os.path.join(temp_path, "temp.zip")
            log_debug(f"Creating temp ZIP: {temp_zip}")
            os.chdir(temp_path)
            log_debug(f"Changed to directory: {os.getcwd()}")
            try:
                # Compress all XML files in one zip command
                subprocess.run(
                    ["zip", "-r", "-Z", "deflate", temp_zip, "."],
                    check=True,
                    capture_output=True,
                    text=True
                )
            except subprocess.CalledProcessError as e:
                error_msg = f"Error recompressing {zip_file}: {e.stderr}"
                log_error(error_msg)
                os.chdir(self.zips_dir)
                return False

            # Verify temp.zip exists
            if not os.path.exists(temp_zip):
                error_msg = f"Error: {temp_zip} was not created for {zip_file}."
                log_error(error_msg)
                os.chdir(self.zips_dir)
                return False

            # Move to output directory using absolute path
            output_zip = os.path.join(self.zips_dir, "recompressed", base_name)
            os.makedirs(os.path.dirname(output_zip), exist_ok=True)
            log_debug(f"Moving {temp_zip} to {output_zip}")
            try:
                shutil.move(temp_zip, output_zip)
            except (OSError, shutil.Error) as e:
                error_msg = f"Error moving {temp_zip} to {output_zip}: {e}"
                log_error(error_msg)
                os.chdir(self.zips_dir)
                return False

            # Return to base directory and clean up
            os.chdir(self.zips_dir)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            log_info(f"Successfully recompressed {zip_file} to recompressed/{base_name}")
            return True

        check_tools()

        # Scan ZIPs - only check files that don't have recompressed versions
        zip_files = glob.glob(os.path.join(self.zips_dir, "20*.zip"))
        if not zip_files:
            raise FileNotFoundError("No ZIP files found matching pattern '20*.zip'.")

        # Filter to only new/unprocessed files
        recompressed_dir = os.path.join(self.zips_dir, "recompressed")
        os.makedirs(recompressed_dir, exist_ok=True)

        to_check = []
        for zip_file in zip_files:
            base_name = os.path.basename(zip_file)
            recompressed_path = os.path.join(recompressed_dir, base_name)
            if not os.path.exists(recompressed_path):
                to_check.append(zip_file)

        if not to_check:
            log_info("All ZIP files already have recompressed versions. Skipping recompression.")
            return True

        log_info(f"Found {len(to_check)} ZIP files to check for recompression.")

        to_recompress = []
        for zip_file in to_check:
            log_debug(f"Checking {zip_file}...")
            needs_recompress, reason = check_compression(zip_file)
            if needs_recompress:
                log_info(f"  {reason}")
                to_recompress.append(zip_file)
            else:
                log_info(f"  {reason}. Skipping.")

        if not to_recompress:
            log_info("No ZIP files need recompression.")
            return

        log_info(f"ZIP files to recompress: {len(to_recompress)}")

        # Recompress
        success_count = 0
        for zip_file in to_recompress:
            if recompress_zip(zip_file):
                success_count += 1
            else:
                log_error(f"Failed to recompress {zip_file}.")
                return False

        log_info(f"Recompression complete. Successfully recompressed {success_count} files.")
        return True

    # Main processing methods that delegate to modules

    def fetch_irs_zips(self, start_year: int, end_year: int):
        """Fetch IRS 990 ZIP files from IRS website and recompress (step 1)"""
        if self.exit_processing:
            log_info("Shutdown requested before starting IRS ZIP fetch")
            return False
        log_info(f"Fetching IRS 990 ZIP files from {start_year} to {end_year}")
        return self.irs_fetch_processor.fetch_irs_zips(start_year, end_year)

    def process_zip_files(self, start_year: int, end_year: int):
        """Process ZIP files and register XML files (step 3)"""
        if self.exit_processing:
            log_info("Shutdown requested before starting ZIP processing")
            return 0
        log_info(f"Processing ZIP files from {start_year} to {end_year}")
        return self.zip_processor.process_zip_files(start_year, end_year)

    def process_bmf_files(self):
        """Process BMF files (step 4)"""
        log_info("Processing BMF files and ingesting into database")
        self.setup_status_gauges(interval=10.0)
  
        # The XMLProcessor already leverages key-value paging via XMLProducer inheriting from BaseProducer
        # XMLProducer._get_work_batch uses last_xml_id for WHERE xml_id > last_xml_id ORDER BY xml_id LIMIT batch_size
        # This ensures concurrent-safe batching without skips/duplicates
        if self.exit_processing:
            log_info("Shutdown requested before starting BMF processing")
            return 0
        result = self.bmf_processor.fetch_and_ingest(self.max_files)
        self.processed_steps += 1
        return result
    
    def run_fec(self):
        """Download FEC bulk files, preprocess, ingest (after xml)."""
        if self.exit_processing:
            log_info("Shutdown requested before FEC")
            return 0
        log_info("Running FEC bulk download + ingest")
        stats = self.fec_processor.run()
        self.processed_steps += 1
        return stats.get("rows_promoted", 0)

    def run_medicare(self):
        """Download CMS NPPES + Medicaid spending, ingest (after xml)."""
        if self.exit_processing:
            log_info("Shutdown requested before Medicare")
            return 0
        log_info("Running Medicare/CMS provider data download + ingest")
        stats = self.medicare_processor.run()
        self.processed_steps += 1
        return stats.get("nppes_providers", 0) + stats.get("spending_rows", 0)

    def run_sanctions(self):
        """Download Treasury OFAC SDN list and ingest (after medicare)."""
        if self.exit_processing:
            log_info("Shutdown requested before sanctions")
            return 0
        log_info("Running Treasury OFAC sanctions download + ingest")
        stats = self.sanctions_processor.run()
        self.processed_steps += 1
        return stats.get("entities", 0)

    def run_dot(self):
        """Download FMCSA motor carrier census and ingest (after sanctions)."""
        if self.exit_processing:
            log_info("Shutdown requested before DOT")
            return 0
        log_info("Running FMCSA DOT carrier census download + ingest")
        stats = self.dot_processor.run()
        self.processed_steps += 1
        return stats.get("carriers", 0)

    def process_xml_files(self):
        """Parse XML files and extract data to dataclasses (step 5)"""
        log_info("Processing XML files and extracting data")
        self.setup_status_gauges(interval=10.0)
  
        # Handle profiling if requested
        if self.profile_seconds:
            return self._profile_xml_processing()
  
        # Dynamic worker adjustment based on available memory
        import psutil
        available_memory_gb = psutil.virtual_memory().available / (1024**3)
        dynamic_workers = max(1, min(self.workers, int(available_memory_gb * 2)))  # Rough heuristic: 0.5GB per worker
        if dynamic_workers < self.workers:
            log_info(f"Reducing workers from {self.workers} to {dynamic_workers} due to low memory ({available_memory_gb:.1f}GB available)")
      
        # The XMLProcessor already leverages key-value paging via XMLProducer inheriting from BaseProducer
        # XMLProducer._get_work_batch uses last_xml_id for WHERE xml_id > last_xml_id ORDER BY xml_id LIMIT batch_size
        # This ensures concurrent-safe batching without skips/duplicates
        if self.exit_processing:
            log_info("Shutdown requested before starting XML processing")
            return 0
        result = self.xml_processor.process_xml_files(self.max_files, dynamic_workers, collect_xpath_stats=self.collect_xpath_stats)
        self.processed_steps += 1
        return result

    def _profile_xml_processing(self):
        """Profile XML processing for a specified number of seconds"""
        import cProfile
        import pstats
        import io
        from datetime import datetime
        import signal
        import threading

        log_info(f"Starting profiling for {self.profile_seconds} seconds during XML processing")

        # Create a timeout event for clean shutdown
        timeout_event = threading.Event()

        def timeout_handler(signum, frame):
            log_info(f"Profiling timeout reached after {self.profile_seconds} seconds")
            timeout_event.set()

        # Set up timeout alarm
        signal.signal(signal.SIGALRM, timeout_handler)
        if self.profile_seconds is not None:
            signal.alarm(self.profile_seconds)

        # Temporarily disable profiling flag to prevent recursion
        original_profile_seconds = self.profile_seconds
        original_global_profile_seconds = global_config.profile_seconds
        self.profile_seconds = None
        global_config.profile_seconds = None

        # Start profiling
        profiler = cProfile.Profile()
        profiler.enable()
        start_time = time.time()

        result = None
        try:
            # Run the actual processing with timeout handling
            result = self.xml_processor.process_xml_files(self.max_files, self.workers, collect_xpath_stats=self.collect_xpath_stats)
        except KeyboardInterrupt:
            log_info("Profiling interrupted by timeout")
            # Signal producers to stop - XMLProcessor doesn't have shutdown_event, use timeout_event instead
            result = None
        finally:
            # Restore profiling flag
            self.profile_seconds = original_profile_seconds
            global_config.profile_seconds = original_global_profile_seconds

            # Cancel the alarm
            signal.alarm(0)

            # Stop profiling
            profiler.disable()
            end_time = time.time()
            execution_time = end_time - start_time

            log_info(f"XML processing profiling complete. Time: {execution_time:.2f}s")

            # Generate profiling report
            self._generate_profiling_report("xml_processing", execution_time, result if result is not None else 0, profiler)

        return result

    def _generate_profiling_report(self, operation_name: str, execution_time: float, work_items_processed: int, profiler):
        """
        Generate profiling report files similar to profile_pipeline.py examples.
        """
        # Get worker count from global config
        worker_count = getattr(global_config, 'workers', 1)

        # Determine run mode suffix
        if global_config.no_backpressure:
            mode_suffix = 'fast' if worker_count > 4 else 'noback'
        else:
            mode_suffix = 'back'

        # Create timestamp for filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Generate filenames with mode suffix
        stats_filename = f"pipeline_profile_{timestamp}_{operation_name}_{worker_count}workers_{mode_suffix}.stats"
        txt_filename = f"pipeline_profile_{timestamp}_{operation_name}_{worker_count}workers_{mode_suffix}.txt"

        # Generate profiling stats
        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
        ps.print_stats(50)  # Top 50 functions by cumulative time
        profiling_output = s.getvalue()

        # Calculate metrics
        processing_rate = work_items_processed / execution_time if execution_time > 0 else 0
        throughput = work_items_processed / execution_time * 60  # items per minute

        # Save stats file
        profiler.dump_stats(stats_filename)

        # Save human-readable report
        with open(txt_filename, "w") as f:
            f.write(f"=== IRS 990 {operation_name.title()} Profiling Report ===\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Execution Time: {execution_time:.2f} seconds\n")
            f.write(f"Work Items Processed: {work_items_processed}\n")
            f.write(f"Processing Rate: {processing_rate:.2f} items/second\n")
            f.write(f"Throughput: {throughput:.2f} items/minute\n")
            f.write(f"Worker Threads: {worker_count}\n\n")
            f.write("=== Top 50 Functions by Cumulative Time ===\n")
            f.write(profiling_output)

        log_info(f"Profiling complete. Results saved to:")
        log_info(f"  - {txt_filename} (human-readable report)")
        log_info(f"  - {stats_filename} (binary stats for further analysis)")
        log_info(f"  - Mode: {mode_suffix} (backpressure={not global_config.no_backpressure}, workers={worker_count})")

        # Print summary to console
        log_info("=== Profiling Summary ===")
        log_info(f"Execution time: {execution_time:.2f} seconds")
        log_info(f"Work items processed: {work_items_processed}")
        log_info(f"Processing rate: {processing_rate:.2f} items/sec")
        log_info(f"Throughput: {throughput:.2f} items/min")
        log_info("Top 10 most time-consuming functions:")
        lines = profiling_output.split('\n')
        for line in lines[:15]:  # First 15 lines contain the top functions
            if line.strip():
                log_info(line)

    def _get_xml_files_to_process(self, last_xml_id: Optional[str] = None, batch_size: int = 100) -> Tuple[List[Tuple[str, str, str, str, int]], Optional[str]]:
        """Get list of XML files to process from database using key-value paging"""
        query = """
            SELECT xml_id, zip_id, filename, internal_path, file_size
            FROM XmlFiles
            WHERE processed = FALSE
        """
        params = (batch_size,)
        if last_xml_id:
            query += " AND xml_id > ?"
            params = (last_xml_id,) + params
        query += " ORDER BY xml_id LIMIT ?"
        result = self.db_ops.execute_query(query, params)
        files = result.fetchall()
        if self.max_files:
            # Apply global max_files limit if set
            total_available = self.db_ops.get_xml_files_to_process_count(processing_version=CURRENT_PROCESSING_VERSION)
            if total_available > self.max_files:
                # For simplicity in this method, limit the batch if needed, but full paging handled in XMLProcessor
                files = files[:self.max_files]
        max_pk = max(row[0] for row in files) if files else None
        return files, max_pk

    def _process_xml_files_parallel(self, initial_files: Optional[List[Tuple]] = None):
        """Process XML files using producer-consumer pattern for threading safety with key-value paging"""
        # This method is deprecated - XML processing is now handled by xml_processor.process_xml_files()
        # Updated to use key-value paging for compatibility, but main path uses XMLProcessor
        if initial_files:
            # For backward compatibility, process initial batch
            self._process_batch(xml_files=initial_files)
        else:
            # Use paging to process all
            last_pk = None
            while True:
                files, new_last_pk = self._get_xml_files_to_process(last_pk, batch_size=100)
                if not files:
                    break
                self._process_batch(xml_files=files)
                last_pk = new_last_pk
                if self.max_files and len(files) >= self.max_files:
                    break
    
    def _process_batch(self, xml_files: List[Tuple]):
        """Process a batch of XML files (internal helper)"""
        # Placeholder for batch processing logic - actual implementation delegated to XMLProcessor
        for xml_id, zip_id, filename, internal_path, file_size in xml_files:
            # Simulate processing - in real use, this would extract and parse
            pass



        return None





    def run_geolocate_census(self):
        """Bulk Census pass for pending rows; misses → pending_api (geolocate step 2a)."""
        if self.exit_processing:
            log_info("Shutdown requested before geolocate_census")
            return 0
        self.setup_status_gauges(interval=MONITOR_INTERVAL_SECONDS)

        if cg is None:
            if not global_config.is_quiet():
                log_warning(
                    "censusgeocode library not available. Skipping geolocate_census. "
                    "Install with: pip install censusgeocode"
                )
            return 0

        try:
            from geolocate_census_processor import GeolocateCensusProcessor
            log_info("Starting geolocate_census (bulk Census; API deferred to geolocate_api)")
            processor = GeolocateCensusProcessor(self.db_ops)
            result = processor.run(max_files=self.max_files)
            self.processed_steps += 1
            return result
        except Exception as e:
            log_error(f"geolocate_census failed: {e}", exc_info=True)
            return 0

    def run_geolocate_api(self):
        """Serial API tail for pending_api rows; misses → grok_pending (geolocate step 2b)."""
        if self.exit_processing:
            log_info("Shutdown requested before geolocate_api")
            return 0
        self.setup_status_gauges(interval=MONITOR_INTERVAL_SECONDS)

        try:
            from geolocate_api_processor import GeolocateApiProcessor
            log_info("Starting geolocate_api (photon/opencage/…; Grok deferred to geolocate_grok)")
            processor = GeolocateApiProcessor(self.db_ops)
            result = processor.run(max_files=self.max_files)
            self.processed_steps += 1
            return result
        except Exception as e:
            log_error(f"geolocate_api failed: {e}", exc_info=True)
            return 0

    def run_geolocate_new(self):
        """Legacy alias — runs geolocate_census then geolocate_api."""
        if self.exit_processing:
            log_info("Shutdown requested before geolocate_new")
            return 0
        log_info("geolocate_new is deprecated; running geolocate_census + geolocate_api")
        census = self.run_geolocate_census()
        if self.exit_processing:
            return census
        api = self.run_geolocate_api()
        return census + api

    def run_geolocate_grok(self):
        """xAI Batch API geocoding for grok_pending + pending_api rows (geolocate step 3)."""
        if self.exit_processing:
            log_info("Shutdown requested before geolocate_grok")
            return 0
        try:
            from geolocate_grok_processor import GeolocateGrokProcessor
            max_rows = global_config.max_files
            log_info(
                f"Starting geolocate_grok (preprocess + xAI batch; "
                f"intake=grok_pending+pending_api; max_rows={max_rows})"
            )
            processor = GeolocateGrokProcessor(self.db_ops)
            result = processor.run(max_rows=max_rows)
            self.processed_steps += 1
            return result
        except Exception as e:
            log_error(f"geolocate_grok failed: {e}", exc_info=True)
            return 0

    def geolocate_addresses(self):
        """Backward-compat alias for run_geolocate_new."""
        return self.run_geolocate_new()

    def run_einless(self):
        """Phonebook exact-core resolution; sets recipient_ein_backfilled (after address, before match)."""
        if self.exit_processing:
            log_info("Shutdown requested before einless")
            return 0
        log_info("Running einless phonebook resolution for no-EIN grantees")
        stats = self.einless_processor.run()
        self.processed_steps += 1
        return stats.get("grants_updated", 0)

    def run_geolocate_prev(self):
        """Archive cache + loose_colocator (geolocate trilogy step 1, before Census API)."""
        if self.exit_processing:
            log_info("Shutdown requested before geolocate_prev")
            return 0
        log_info("Running geolocate_prev (archive cache + loose colocator)")
        result = self.geolocate_prev_processor.run(max_files=self.max_files)
        self.processed_steps += 1
        return result

    def run_geolocate1(self):
        """Backward-compat alias for run_geolocate_prev."""
        return self.run_geolocate_prev()

    def run_geolocate_archive(self):
        """Export successful geocodes → geocode_archive_distinct.tsv.gz (trilogy step 3)."""
        if self.exit_processing:
            log_info("Shutdown requested before geolocate_archive")
            return 0
        log_info("Running geolocate_archive (export geocode archive TSV)")
        result = self.geolocate_archive_processor.run()
        self.processed_steps += 1
        return result

    def process_officer_photos(self):
        """Process officer photos using Google Knowledge Graph API (step 8)"""
        if self.exit_processing:
            log_info("Shutdown requested before starting officer processing")
            return 0
        log_info("Starting officer deduplication")
        dedup_result = self.officer_dedup_processor.deduplicate_officers()
        log_info(f"Officer deduplication complete. Processed {dedup_result} duplicates.")
  
        log_info("Processing officer photos using Google Knowledge Graph API")
        return self.photo_processor.process_officer_photos()

    def _geolocate_batch(self, batch: List[Tuple]) -> List[Tuple]:
        """Geolocate a batch of addresses"""
        # This method is now handled by geolocation_processor.py
        return []

    def match_grants(self):
        """Match grants with unknown EINs by address or colocator (step 9)"""
        if self.exit_processing:
            log_info("Shutdown requested before starting grant matching")
            return 0
        log_info("Matching grants with unknown EINs by address/colocator")
        return self.address_matcher.match_grants()

    def _find_charity_by_address(self, name: str, address: str, zip_code: str, po_box: str, tax_year: int) -> Optional[str]:
        """Find charity EIN by address/colocator matching"""
        # This method is now handled by address_matcher.py
        return None

    def _create_stub_charity(self, name: str, address: str, zip_code: str, po_box: str, tax_year: int) -> Optional[str]:
        """Create a stub charity record for unmatched grants"""
        # This method is now handled by address_matcher.py
        return None

    def calculate_percentiles(self):
        """Calculate percentile rankings by org type and tax year (step 10)"""
        if self.exit_processing:
            log_info("Shutdown requested before starting percentile calculation")
            return 0
        log_info("Calculating percentile rankings")
        return self.percentile_calculator.calculate_percentiles()

    def calculate_ratios(self):
        """Calculate percentages by org type and tax year (step 10)"""
        if self.exit_processing:
            log_info("Shutdown requested before starting percentile calculation")
            return 0
        log_info("Calculating percentile rankings")
        return self.percentile_calculator.compute_ratios()

    def _calculate_percentile(self, value: float, sorted_values: List[float]) -> float:
        """Calculate percentile rank for a value in a sorted list"""
        # This method is now handled by percentile_calculator.py
        return 0.0

    def deduplicate_addresses(self):
        """Deduplicate addresses and create master-child relationships (step 4)"""
        if self.exit_processing:
            log_info("Shutdown requested before starting address deduplication")
            return 0
        log_info("Deduplicating addresses and creating master-child relationships")
        return self.address_dedup_processor.deduplicate_addresses()

    def export_final_tsvs(self):
        """Export final TSV files (step 11)"""
        if self.exit_processing:
            log_info("Shutdown requested before starting export")
            return
        log_info("Exporting final TSV files")
        self.tsv_exporter.export_final_tsvs()

    def extract_xml_files(self, eins: List[str], dest_dir: str):
        """Extract XML files for specified EINs (utility function)"""
        log_info(f"Extracting XML files for {len(eins)} EINs to {dest_dir}")
        return self.extract_processor.extract_xml_files(eins, dest_dir)


def main():
    """Command-line interface"""
    # Enable faulthandler for better stack traces on crashes
    faulthandler.enable()

    parser = argparse.ArgumentParser(description="IRS 990 Data Processor")
    parser.add_argument("--start-year", type=int, default=2017, help="Start year for processing (default: 2017)")
    parser.add_argument("--end-year", type=int, default=2030, help="End year for processing (default: 2030)")
    parser.add_argument("--zips-dir", default=DEFAULT_ZIPS_DIR, help="ZIP files directory")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Output directory")
    parser.add_argument("--anal-dir", default=DEFAULT_ANAL_DIR, help="Analysis directory")
    parser.add_argument("--final-dir", default=DEFAULT_FINAL_DIR, help="Final output directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode - minimal logging")
    parser.add_argument("--max-files", type=int, default=None, help="Maximum number of XML files to process (default: no limit)")
    parser.add_argument("--log-sql", action="store_true", help="Enable SQL logging (implies --verbose)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"Number of worker threads (default: {MAX_WORKERS})")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Database path (default: irs990.duckdb)")
    parser.add_argument("--dbUI", action="store_true", help="Start database UI alongside processing")
    parser.add_argument("--profile", type=int, help="Profile currently executing step (collect_operations or execute_operations_batch) for N seconds and exit")
    _step_choices = PIPELINE_STEPS + list(STEP_ALIASES.keys())
    parser.add_argument("--step", choices=["all"] + _step_choices,
                          default="all", help="Processing step to run (deprecated: use --start-step and --stop-step)")
    parser.add_argument("--start-step", choices=_step_choices, help="Starting step for processing")
    parser.add_argument("--stop-step", choices=_step_choices, help="Stopping step for processing")
    parser.add_argument("--progress", choices=["files", "bytes"], default="files",
                           help="Progress tracking type (default: files)")
    parser.add_argument("--extract", nargs='+', help="List of EINs to extract XML files for")
    parser.add_argument("--extract-dest", help="Destination directory for extracted XML files")
    parser.add_argument("--nostats", action="store_true", help="Skip stats report generation after each step")
    parser.add_argument("--no-backpressure", action="store_true", help="Disable backpressure mechanism for producer threads")
    parser.add_argument("--collect-xpath-stats", action="store_true", help="Collect XPath performance statistics (only in thread 0 to avoid race conditions)")
    parser.add_argument("--db-threads", type=int, default=4,   help="Threads for DuckDB (may only matter for 1.5+?)")

    args = parser.parse_args()

    steps = PIPELINE_STEPS

    step_actions = {
        "irsfetch": lambda: processor.fetch_irs_zips(args.start_year, args.end_year),
        "zip": lambda: processor.process_zip_files(args.start_year, args.end_year),
        "xml": lambda: processor.process_xml_files(),
        "bmf": lambda: processor.process_bmf_files(),
        "fec": lambda: processor.run_fec(),
        "medicare": lambda: processor.run_medicare(),
        "sanctions": lambda: processor.run_sanctions(),
        "dot": lambda: processor.run_dot(),
        "address": lambda: processor.deduplicate_addresses(),
        "einless": lambda: processor.run_einless(),
        "match": lambda: processor.match_grants(),
        "geolocate_prev": lambda: processor.run_geolocate_prev(),
        "geolocate_census": lambda: processor.run_geolocate_census(),
        "geolocate_api": lambda: processor.run_geolocate_api(),
        "geolocate_new": lambda: processor.run_geolocate_new(),
        "geolocate_grok": lambda: processor.run_geolocate_grok(),
        "geolocate_archive": lambda: processor.run_geolocate_archive(),
        "geolocate": lambda: processor.run_geolocate_new(),
        "geolocate1": lambda: processor.run_geolocate_prev(),
        "grant_match": lambda: processor.grant_match_processor.match_grants(),
        "photos": lambda: processor.process_officer_photos(),
        "backfill": lambda: processor.backfill_charities_processor.backfill_charities(),
        "ratios": lambda: processor.calculate_ratios(),
        "percentiles": lambda: processor.calculate_percentiles(),
        "export": lambda: processor.export_final_tsvs()
    }

    # Handle backward compatibility with --step
    if args.step != "all":
        args.start_step = args.step
        args.stop_step = args.step

    if not args.start_step:
        args.start_step = "irsfetch"
    if not args.stop_step:
        args.stop_step = "export"

    for raw_step in (args.start_step, args.stop_step, args.step):
        if raw_step in STEP_ALIASES:
            log_warning(f"Step '{raw_step}' is deprecated — use '{STEP_ALIASES[raw_step]}'")
    args.start_step = normalize_step(args.start_step)
    args.stop_step = normalize_step(args.stop_step)

    if steps.index(args.start_step) > steps.index(args.stop_step):
        parser.error("--start-step must come before --stop-step in the processing order")

    # Set global config from parsed args
    global_config.set_from_args(args)
    update_logging_config()

    # If --log-sql is specified, force verbose mode for SQL logging
    if args.log_sql:
        global_config.verbose = True

    processor = IRS990Processor(
        db_path=global_config.db_path,
        zips_dir=global_config.zips_dir,
        out_dir=global_config.out_dir,
        anal_dir=global_config.anal_dir,
        final_dir=global_config.final_dir,
        verbose=global_config.verbose,
        quiet=global_config.quiet,
        max_files=global_config.max_files,
        log_sql=global_config.log_sql,
        workers=global_config.workers,
        dbUI=global_config.dbUI,
        profile_seconds=global_config.profile_seconds,
        nostats=global_config.nostats,
        no_backpressure=global_config.no_backpressure,
        collect_xpath_stats=global_config.collect_xpath_stats
    )

    # Handle extract mode
    if args.extract and args.extract_dest:
        log_info(f"Extracting XML files for EINs: {args.extract}")
        result = processor.extract_xml_files(args.extract, args.extract_dest)
        log_info(f"Extraction complete. Extracted {result} files.")
        sys.exit(0)

    # Handle profiling mode
    if args.profile:
        log_info(f"Running profiling for {args.profile} seconds on currently executing step...")
        # The profiling is now handled automatically by the base classes when global_config.profile_seconds is set
        # Just run the normal processing and let the base classes handle the profiling
        result = processor.process_xml_files()
        log_info(f"Profiling complete. Results saved to profile files.")
        sys.exit(0)

    try:
        # Execute steps from start_step to stop_step
        start_idx = steps.index(args.start_step)
        stop_idx = steps.index(args.stop_step)

        for i in range(start_idx, stop_idx + 1):
            if processor.exit_processing:
                log_info("Shutdown requested during processing steps")
                break
            step = steps[i]
            log_info(f"Starting step: {step}")
            action = step_actions[step]
            if action:
                action()
            log_info(f"Completed step: {step}")
 
            # Optimize after each major step — skip for chunked overnight loops
            # (ANALYZE Addresses/Geocoding can take longer than the work itself).
            skip_opt = (
                os.environ.get("SKIP_POST_STEP_OPTIMIZE", "").strip() in ("1", "true", "yes")
                or (getattr(processor, "max_files", None) is not None and int(processor.max_files or 0) > 0)
            )
            if skip_opt:
                log_info(f"Skipping optimize_database after {step} (chunked/SKIP_POST_STEP_OPTIMIZE)")
            else:
                log_info(f"Optimizing database after {step}")
                print(f"DEBUG: About to call optimize_database after {step}")
                processor.db_ops.optimize_database()
                print(f"DEBUG: optimize_database completed after {step}")
 
            # Generate stats report after each step (unless --nostats is specified)
            if not global_config.nostats:
                try:
                    log_info(f"Generating stats report for step: {step}")
                    report_file = processor.stats_processor.generate_stats_report(f"after_{step}", f"Completed step: {step}")
                    log_info(f"Stats report generated successfully: {report_file}")
                except Exception as e:
                    log_error(f"Failed to generate stats report for step {step}: {e}", exc_info=True)
                    # Don't exit on stats failure - continue processing
                    if not processor.quiet:
                        log_warning(f"Continuing processing despite stats report failure for step {step}")

    except Exception as e:
        if not processor.quiet:
            log_error(f"Processing failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
    sys.exit(0) #brute force exit to ensure all threads are killed and we don't hang on shutdownang on shutdown