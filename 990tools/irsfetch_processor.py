#!/usr/bin/env python3
"""
irsfetch_processor.py - IRS ZIP file download and recompression processor

This module handles downloading IRS 990 ZIP files from the IRS website
and recompressing them to standard format for processing.
"""

import os
import sys
import argparse
import time
import zipfile
import shutil
import subprocess
import glob
import re
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from bs4 import BeautifulSoup, Tag
import queue

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# Import logging utilities
from logging_utils import log_info, log_error, log_debug, log_warning
from config import global_config

# Import producer-consumer pattern classes
from base_processor import BaseProcessor, BaseProducer, BaseConsumer, ThreadPoolManager, ThreadPoolConfig, PoolConfig
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from pending_database_context import PendingDatabaseContext
from queue_status_display import QueueStatusDisplay


class IRSFetchProducer(BaseProducer):
    """Producer for IRS ZIP file download operations"""

    def __init__(self, db_ops: DatabaseOperations, zips_dir: str = "/Volumes/Data/irs_zips"):
        super().__init__(db_ops, batch_size=10)  # Small batches for years
        self.zips_dir = zips_dir
        self.min_year = 2017
        self.max_year = 2030

        # Ensure zips directory exists
        if not os.path.exists(self.zips_dir):
            os.makedirs(self.zips_dir)

    def get_progress_scope(self, bytes: bool = False) -> Dict[str, Any]:
        """Estimate total IRS files needing download and return appropriate unit"""
        avg_zips_per_year = 4
        estimated_years = 14
        estimated_files = estimated_years * avg_zips_per_year

        if bytes:
            avg_zip_size_bytes = 50 * 1024 * 1024
            total = estimated_files * avg_zip_size_bytes
            unit = "bytes"
        else:
            total = estimated_files
            unit = "files"

        return {"total": total, "unit": unit}

    def _get_work_batch(self, last_pk: Optional[int] = None) -> Tuple[List[Tuple[int, str]], Optional[int]]:
        start_year = last_pk + 1 if last_pk is not None else self.min_year
        batch = []
        end_year = min(start_year + self.batch_size, self.max_year + 1)
        for year in range(start_year, end_year):
            batch.append((year, "download"))
        if batch:
            max_pk = max(year for year, _ in batch)
        else:
            max_pk = None
        return batch, max_pk

    def _process_work_batch_to_context(self, batch: List[Tuple[int, str]]) -> Optional['PendingDatabaseContext']:
        from pending_database_context import PendingDatabaseContext

        contexts = []

        for year, operation_type in batch:
            if operation_type == "download":
                context = PendingDatabaseContext()
                progress_op = DatabaseOperation(
                    operation_type=DatabaseOperationType.PROGRESS_UPDATE,
                    data={"count": 1}
                )
                context.addOperationToDatabase(progress_op)
                contexts.append(context)

        if not contexts:
            return None
        return self.merge_pending_contexts(contexts)


class IRSFetchConsumer(BaseConsumer):
    """Consumer for IRS ZIP file operations"""

    def __init__(self, db_ops: DatabaseOperations, zips_dir: str = "/Volumes/Data/irs_zips"):
        super().__init__(db_ops)
        self.zips_dir = zips_dir
        self.downloaded_zips = 0

    def _process_operations_batch(self, operations_by_type):
        pass

    def _execute_zip_operation(self, operation):
        data = operation.data
        year = data["year"]
        zips_dir = data["zips_dir"]
        operation_type = data["operation"]

        if operation_type == "download_and_recompress":
            self._download_and_recompress_year(year, zips_dir)

    def _execute_operations_batch(self, operations):
        self.execute_operations_batch(operations)

    def _download_and_recompress_year(self, year: int, zips_dir: str, urls: Optional[List[str]] = None):
        """Download and recompress ZIP files for a specific year"""
        log_info(f"Processing year {year}")

        if urls is None:
            urls = []

        # Download ZIP files using curl (urls pre-scraped)
        if not self._download_urls(urls, zips_dir):
            log_error(f"Failed to download ZIP files for {year}")
            return False

        # Recompress ZIP files
        if not self._recompress_zips(zips_dir):
            log_error(f"Failed to recompress ZIP files for {year}")
            return False

        log_info(f"Successfully processed year {year}")
        return True

    def _download_urls(self, urls: List[str], dest_folder: str) -> bool:
        """Download a list of URLs using curl (reliable, with retries).

        Treats missing, zero-byte, and tiny stub files as not present so a
        failed partial (or empty 200) never blocks re-download forever.
        """
        # IRS monthly TEOS zips are typically tens–hundreds of MB; anything
        # under this is almost certainly a stub / failed write.
        MIN_VALID_ZIP_BYTES = 1024

        downloaded = 0
        for url in urls:
            if self.exit_processing:
                return False
            filename = url.split('/')[-1]
            dest_path = os.path.join(dest_folder, filename)
            if os.path.exists(dest_path):
                try:
                    size = os.path.getsize(dest_path)
                except OSError:
                    size = 0
                if size >= MIN_VALID_ZIP_BYTES:
                    log_info(f"Skipping {filename} - already exists ({size:,} bytes)")
                    continue
                log_warning(
                    f"Removing bogus {filename} ({size} bytes) before re-download"
                )
                try:
                    os.unlink(dest_path)
                except OSError as e:
                    log_error(f"Could not remove bogus {dest_path}: {e}")
                    return False

            # Use curl with retries, follow redirects, fail on error.
            # max-time is per-attempt; large monthly zips can exceed 5 minutes.
            cmd = [
                "curl", "-L", "--fail", "--retry", "3", "--retry-delay", "5",
                "--connect-timeout", "30", "--max-time", "1800",
                "-o", dest_path, url
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                try:
                    size = os.path.getsize(dest_path)
                except OSError:
                    size = 0
                if size < MIN_VALID_ZIP_BYTES:
                    log_error(
                        f"Downloaded {filename} is bogus ({size} bytes) — removing"
                    )
                    if os.path.exists(dest_path):
                        os.unlink(dest_path)
                    return False
                log_info(f"Downloaded {filename} ({size:,} bytes)")
                downloaded += 1
            except subprocess.CalledProcessError as e:
                log_error(f"Failed to download {url}: {e.stderr}")
                if os.path.exists(dest_path):
                    os.unlink(dest_path)  # clean partial file
                return False

        self.downloaded_zips += downloaded
        return True

    def _recompress_zips(self, zips_dir: str):
        """Recompress ZIP files to standard format using 7z and zip"""
        def check_tools():
            for tool in ["7z", "zip", "curl"]:
                if shutil.which(tool) is None:
                    raise RuntimeError(f"Error: {tool} is not installed. Please install it (e.g. brew install {tool} on macOS, apt install {tool} on Linux).")

        def check_compression(zip_file):
            try:
                with zipfile.ZipFile(zip_file, "r") as zf:
                    for file_info in zf.infolist():
                        if file_info.compress_type not in (0, 8):
                            return True, f"Unsupported compression type {file_info.compress_type} in {file_info.filename}"
                return False, "All files use supported compression (Stored or Deflated)"
            except zipfile.BadZipFile as e:
                return True, f"Malformed ZIP file: {e}"
            except Exception as e:
                return True, f"Error reading ZIP: {e}"

        def recompress_zip(zip_file):
            """Recompress a single ZIP file *in place* (overwrite original with standard version)."""
            base_name = os.path.basename(zip_file)
            log_info(f"Recompressing {zip_file} in place...")
            original_cwd = os.getcwd()
            temp_dir = os.path.join(zips_dir, "temp")
            temp_path = temp_dir
            temp_zip = os.path.join(temp_path, "temp.zip")

            try:
                # Clean and prepare temp directory
                if os.path.exists(temp_dir):
                    for item in Path(temp_dir).glob("*"):
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                os.makedirs(temp_dir, exist_ok=True)

                # Extract with 7z (supports all compression types)
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

                extracted_files = len(list(Path(temp_path).rglob("*.xml")))
                log_info(f"Extracted {extracted_files} files from {zip_file}.")

                # Recompress everything using standard Deflate
                log_debug(f"Creating temp ZIP: {temp_zip}")
                os.chdir(temp_path)
                log_debug(f"Changed to directory: {os.getcwd()}")
                try:
                    subprocess.run(
                        ["zip", "-r", "-Z", "deflate", temp_zip, "."],
                        check=True,
                        capture_output=True,
                        text=True
                    )
                except subprocess.CalledProcessError as e:
                    error_msg = f"Error recompressing {zip_file}: {e.stderr}"
                    log_error(error_msg)
                    return False

                if not os.path.exists(temp_zip):
                    error_msg = f"Error: {temp_zip} was not created for {zip_file}."
                    log_error(error_msg)
                    return False

                # Move the new standard ZIP *into place* - overwriting the original incompatible one
                log_debug(f"Moving {temp_zip} to {zip_file} (replacing original in place)")
                try:
                    shutil.move(temp_zip, zip_file)
                except (OSError, shutil.Error) as e:
                    error_msg = f"Error moving {temp_zip} to {zip_file}: {e}"
                    log_error(error_msg)
                    return False

                log_info(f"Successfully recompressed {zip_file} in place (now Python-compatible)")
                return True

            except Exception as e:
                log_error(f"Unexpected error during recompression of {zip_file}: {e}", exc_info=True)
                return False

            finally:
                # ALWAYS restore original working directory and clean up temp dir (even on error)
                try:
                    os.chdir(original_cwd)
                except Exception:
                    pass
                if os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception:
                        pass  # will be cleaned on next run

        check_tools()

        zip_files = glob.glob(os.path.join(zips_dir, "20*.zip"))
        if not zip_files:
            raise FileNotFoundError("No ZIP files found matching pattern '20*.zip'.")

        log_info(f"Found {len(zip_files)} ZIP files to check for recompression.")

        to_recompress = []
        for zip_file in zip_files:
            log_debug(f"Checking {zip_file}...")
            needs_recompress, reason = check_compression(zip_file)
            if needs_recompress:
                log_info(f"  {reason}")
                to_recompress.append(zip_file)
            else:
                log_info(f"  {reason}. Skipping.")

        if not to_recompress:
            log_info("No ZIP files need recompression.")
            return True

        log_info(f"ZIP files to recompress: {len(to_recompress)}")

        success_count = 0
        for zip_file in to_recompress:
            if self.exit_processing:
                log_info("Shutdown requested during ZIP recompression")
                return False
            if recompress_zip(zip_file):
                success_count += 1
            else:
                log_error(f"Failed to recompress {zip_file}.")
                # Continue processing remaining files (do not abort entire batch on one failure)

        log_info(f"Recompression complete. Successfully recompressed {success_count} of {len(to_recompress)} files.")
        return True


class IRSFetchProcessor(BaseProcessor):
    """Processor for downloading and recompressing IRS ZIP files using producer-consumer pattern"""
  
    def __init__(self, zips_dir: str = "/Volumes/Data/irs_zips", db_path: str = "irs990.db"):
        self.db_ops = DatabaseOperations(db_path=db_path, read_only=False)
        super().__init__(self.db_ops)
        self.zips_dir = zips_dir
        self.downloaded_zips = 0
  
        self.producer = IRSFetchProducer(self.db_ops, zips_dir)
        self.consumer = IRSFetchConsumer(self.db_ops, zips_dir)
  
        thread_config = ThreadPoolConfig(
            producer_config=PoolConfig(max_workers=2, queue_size=20),
            consumer_config=PoolConfig(max_workers=1, queue_size=10)
        )
        self.thread_pool_manager = ThreadPoolManager(thread_config, self)

        self.queue_status_display = None

        if not os.path.exists(self.zips_dir):
            os.makedirs(self.zips_dir)

    def _get_custom_metrics(self) -> Dict[str, Any]:
        return {'downloaded_zips': self.downloaded_zips}

    def _scrape_irs_zip_links(self, start_year: int, end_year: int) -> Dict[int, List[str]]:
        """Scrape the IRS page ONCE and return year -> list of full URLs"""
        log_info("Scraping IRS ZIP links (once)...")
        base_url = "https://www.irs.gov/charities-non-profits/form-990-series-downloads"
        
        # Use curl to fetch the page (more reliable than requests in some environments)
        try:
            result = subprocess.run(
                ["curl", "-L", "--fail", "--retry", "2", "--connect-timeout", "30", "-s", base_url],
                check=True,
                capture_output=True,
                text=True
            )
            html = result.stdout
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to fetch IRS page: {e}")
            return {}

        soup = BeautifulSoup(html, 'html.parser')

        zip_links_by_year: Dict[int, List[str]] = {}
        for a in soup.find_all('a', href=True):
            if isinstance(a, Tag):
                href = a.get('href')
                if href and isinstance(href, str) and href.endswith('.zip') and 'TEOS_XML' in href:
                    year_match = re.search(r'(\d{4})', href)
                    if year_match:
                        year = int(year_match.group(1))
                        if start_year <= year <= end_year:
                            if year not in zip_links_by_year:
                                zip_links_by_year[year] = []
                            full_url = f"https://www.irs.gov{href}" if href.startswith('/') else href
                            zip_links_by_year[year].append(full_url)

        log_info(f"Found ZIP links for {len(zip_links_by_year)} years")
        return zip_links_by_year

    def fetch_irs_zips(self, start_year: int, end_year: int) -> bool:
        """Download and recompress IRS 990 ZIP files from IRS website"""
        log_info(f"Fetching IRS 990 ZIP files from {start_year} to {end_year}")
        self.setup_status_gauges(interval=10.0)

        import queue
        monitoring_queue = queue.Queue()
        self.queue_status_display = QueueStatusDisplay(monitoring_queue, update_interval=30.0)
        self.queue_status_display.start()

        try:
            # === SCRAPE ONCE ===
            zip_links_by_year = self._scrape_irs_zip_links(start_year, end_year)

            # Process each year sequentially using pre-scraped links
            for year in range(start_year, end_year + 1):
                if self.exit_processing:
                    log_info("Shutdown requested during IRS ZIP fetch")
                    return False

                urls = zip_links_by_year.get(year, [])
                if not urls:
                    log_warning(f"No ZIP files found for {year}")
                    continue

                success = self._download_and_recompress_year(year, self.zips_dir, urls)
                if not success:
                    log_error(f"Failed to process year {year}")
                    return False
  
            log_info("IRS ZIP file fetch and recompression complete")

            if self.queue_status_display:
                self.queue_status_display.stop()

            return True

        except Exception as e:
            log_error(f"IRS fetch processing failed: {e}", exc_info=True)
            if self.queue_status_display:
                self.queue_status_display.stop()
            return False

    def _download_and_recompress_year(self, year: int, zips_dir: str, urls: List[str]) -> bool:
        """Download and recompress ZIP files for a specific year (urls pre-scraped)"""
        log_info(f"Processing year {year}")

        if not self.consumer._download_urls(urls, zips_dir):
            log_error(f"Failed to download ZIP files for {year}")
            return False

        if not self.consumer._recompress_zips(zips_dir):
            log_error(f"Failed to recompress ZIP files for {year}")
            return False

        log_info(f"Successfully processed year {year}")
        return True

    def _producer_wrapper(self, work_items: List[Tuple[int, str]], work_queue, result_queue, thread_id: int, num_threads: int):
        try:
            log_debug(f"Producer thread {thread_id} starting")
            for i in range(thread_id, len(work_items), num_threads):
                year, operation_type = work_items[i]
                operation = DatabaseOperation(
                    operation_type=DatabaseOperationType.INSERT_ZIP_FILE,
                    data={
                        "year": year,
                        "zips_dir": self.zips_dir,
                        "operation": "download_and_recompress"
                    }
                )
                result_queue.put(operation)
                log_debug(f"Producer {thread_id}: queued operation for year {year}")
        except Exception as e:
            log_error(f"Producer thread {thread_id} error: {e}", exc_info=True)
        finally:
            result_queue.put(None)

    def _consumer_wrapper(self, result_queue, thread_id: int, num_producers: int):
        try:
            log_debug(f"Consumer thread {thread_id} starting")
            sentinels_received = 0
            while True:
                try:
                    operation = result_queue.get(timeout=1.0)
                    if operation is None:
                        sentinels_received += 1
                        if sentinels_received >= num_producers:
                            break
                        continue
                    if isinstance(operation, DatabaseOperation):
                        self.consumer._execute_zip_operation(operation)
                    result_queue.task_done()
                except queue.Empty:
                    if self.thread_pool_manager and self.thread_pool_manager.exit_processing:
                        break
                    continue
        except Exception as e:
            log_error(f"Consumer thread {thread_id} error: {e}", exc_info=True)
        finally:
            pass

    # Legacy compatibility
    def _download_irs_zips(self, start_year: int, end_year: int):
        return True  # Now handled via pre-scraped URLs

    def _recompress_zips(self):
        return self.consumer._recompress_zips(self.zips_dir)
    
    
def main():
    """Command-line interface for IRS fetch processor"""
    parser = argparse.ArgumentParser(description="IRS ZIP File Fetch and Recompress Processor")
    parser.add_argument("--start-year", type=int, default=2017, help="Start year for fetching (default: 2017)")
    parser.add_argument("--end-year", type=int, default=2030, help="End year for fetching (default: 2030)")
    parser.add_argument("--zips-dir", default="/Volumes/Data/irs_zips", help="ZIP files directory")
    parser.add_argument("--db-path", default="irs990.db", help="Database path")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode - minimal logging")

    args = parser.parse_args()

    if args.quiet:
        global_config.quiet = True

    processor = IRSFetchProcessor(zips_dir=args.zips_dir, db_path=args.db_path)

    try:
        success = processor.fetch_irs_zips(args.start_year, args.end_year)
        if success:
            log_info("IRS fetch processing completed successfully")
            sys.exit(0)
        else:
            log_error("IRS fetch processing failed")
            sys.exit(1)
    except Exception as e:
        log_error(f"IRS fetch processing failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if hasattr(processor, 'db_ops'):
            processor.db_ops.close()


if __name__ == "__main__":
    main()