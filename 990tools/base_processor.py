#!/usr/bin/env python3
"""
base_processor.py - Base classes for processor implementations

This module contains base classes that provide common functionality
for all processor implementations in the IRS 990 processing system.
"""

import sys
import cProfile
import pstats
import io
import time
import threading
import queue
import signal
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable, Tuple
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from pending_database_context import PendingDatabaseContext
from logging_utils import log_error, log_info, log_debug, log_warning, start_progress_reporting
from config import global_config
import psutil
import gc
import time
import queue

from enum import Enum
import time
from pending_database_context import PendingDatabaseContext
from constants import BATCH_SIZE, CONSUMER_BATCH_SIZE, MONITOR_INTERVAL_SECONDS, OPTIMIZE_THRESHOLD, GEOCODING_MAX_UPDATES_PER_BATCH, CONSUMER_MAX_IDLE_SECONDS, CONSUMER_POLL_TIMEOUT
from logging_utils import start_progress_reporting
from queue_status_display import QueueStatusDisplay

class PoolConfig:
    """
    Configuration for a thread pool.

    Defines the parameters for managing a pool of worker threads,
    including the number of workers, queue size, batch size, and timeouts.
    """

    def __init__(self,
                 max_workers: int = 4,
                 queue_size: int = 1000,
                 batch_size: int = 100,
                 stall_threshold: int = 30,
                 shutdown_timeout: float = 30.0):
        """
        Initialize pool configuration.

        Args:
            max_workers: Maximum number of worker threads
            queue_size: Maximum size of the work queue
            batch_size: Size of batches for processing
            stall_threshold: Time in seconds before considering a worker stalled
            shutdown_timeout: Time in seconds to wait for threads to shutdown
        """
        self.max_workers = max_workers
        self.queue_size = queue_size
        self.batch_size = batch_size
        self.stall_threshold = stall_threshold
        self.shutdown_timeout = shutdown_timeout


class ThreadPoolConfig:
    """
    Configuration for thread pool management.

    Defines the overall configuration for thread pool operations,
    including producer and consumer pool configurations.
    """

    def __init__(self,
                 producer_config: PoolConfig = None,
                 consumer_config: PoolConfig = None,
                 enable_profiling: bool = False):
        """
        Initialize thread pool configuration.

        Args:
            producer_config: Configuration for producer thread pool
            consumer_config: Configuration for consumer thread pool
            enable_profiling: Whether to enable profiling for thread operations
        """
        self.producer_config = producer_config or PoolConfig()
        self.consumer_config = consumer_config or PoolConfig(max_workers=1)  # Single consumer for DB safety
        self.enable_profiling = enable_profiling


class ThreadPoolManager:
    """
    Generalized thread pool manager for producer-consumer patterns.

    Manages worker threads, work queues, and coordination between producers
    and consumers. Ensures thread-safe operations and proper shutdown handling.
    """

    def __init__(self, config: ThreadPoolConfig, processor: 'BaseProcessor'):
        """
        Initialize the thread pool manager.

        Args:
            config: Thread pool configuration
            processor: BaseProcessor instance that owns this manager
        """
        self.config = config
        self.processor = processor
        self.work_queue = queue.Queue(maxsize=config.producer_config.queue_size)
        self.result_queue = queue.Queue(15_000) # maxsize = config.producer_config.queue_size * self.config.producer_config.max_workers )
        self.producer_threads = []
        self.consumer_threads = []
        self._lock = threading.Lock()

    def start_producer_pool(self, work_items: List[Any], producer_func: Callable, *args, **kwargs) -> None:
        """
        Start producer threads to process work items.

        Args:
            work_items: List of items to be processed by producers
            producer_func: Function to be executed by each producer thread
            *args: Additional positional arguments for producer_func
            **kwargs: Additional keyword arguments for producer_func
        """
        # Clear producer threads from previous runs to prevent accumulation
        self.producer_threads.clear()
        num_producers = min(self.config.producer_config.max_workers, len(work_items))
        log_info(f"Starting {num_producers} producer threads (max_workers={self.config.producer_config.max_workers}, work_items={len(work_items)})")

        for i in range(num_producers):
            thread = threading.Thread(
                target=self._producer_wrapper,
                args=(work_items, producer_func, i, num_producers, args, kwargs)
            )
            thread.daemon = True
            self.producer_threads.append(thread)
            thread.start()

    def start_consumer_pool(self, consumer_func: Callable, num_producers: int = 1, *args, **kwargs) -> None:
        """
        Start consumer threads to process results.

        Args:
            consumer_func: Function to be executed by each consumer thread
            num_producers: Number of producer threads (for sentinel counting)
            *args: Additional positional arguments for consumer_func
            **kwargs: Additional keyword arguments for consumer_func
        """
        num_consumers = 1 #self.config.consumer_config.max_workers There can be only one consumer for database safety
        log_info(f"Starting {num_consumers} consumer threads")

        for i in range(num_consumers):
            thread = threading.Thread(
                target=self._consumer_wrapper,
                args=(consumer_func, i, num_producers, args, kwargs)
            )
            thread.daemon = False  # Consumer threads must not be daemon threads for proper shutdown
            self.consumer_threads.append(thread)
            thread.start()

    def wait_for_completion(self) -> None:
        """
        Wait for all producer and consumer threads to complete.
        """
        # Wait for producers to finish
        log_info("Waiting for producer threads to complete...")
        for i, thread in enumerate(self.producer_threads):
            thread.join()  # Wait indefinitely for producer threads (they are daemon threads)
            log_debug(f"Producer thread {i} completed")

        # Wait for consumers to finish
        log_info("Waiting for consumer threads to complete...")
        for i, thread in enumerate(self.consumer_threads):
            thread.join()  # Wait indefinitely for consumer threads (they are now non-daemon)
            log_debug(f"Consumer thread {i} completed")

    def shutdown(self) -> None:
        """
        Shutdown the thread pool manager and clean up resources.
        """
        log_info("Shutting down thread pool manager")
        BaseProcessor.exit_processing = True  # Set processor exit flag

        # Wait for threads to finish
        self.wait_for_completion()

        # Clear thread lists
        self.producer_threads.clear()
        self.consumer_threads.clear()

    def _producer_wrapper(self, work_items: List[Any], producer_func: Callable,
                          thread_id: int, num_threads: int, args: tuple, kwargs: dict) -> None:
        """
        Wrapper for producer thread execution.

        Args:
            work_items: List of work items to process
            producer_func: Producer function to execute
            thread_id: ID of this producer thread
            num_threads: Total number of producer threads
            args: Additional positional arguments
            kwargs: Additional keyword arguments
        """
        try:
            log_debug(f"Producer thread {thread_id} starting")
            producer_func(work_items, self.work_queue, self.result_queue,
                          thread_id, num_threads, *args, **kwargs)
            log_debug(f"Producer thread {thread_id} completed")
        except Exception as e:
            log_error(f"Producer thread {thread_id} error: {e}", exc_info=True)

    def _consumer_wrapper(self, consumer_func: Callable, thread_id: int, num_producers: int,
                           args: tuple, kwargs: dict) -> None:
        """
        Wrapper for consumer thread execution.

        Args:
            consumer_func: Consumer function to execute
            thread_id: ID of this consumer thread
            num_producers: Number of producer threads (for sentinel counting)
            args: Additional positional arguments
            **kwargs: Additional keyword arguments
        """
        try:
            log_debug(f"Consumer thread {thread_id} starting")
            consumer_func(self.result_queue, thread_id, num_producers, *args, **kwargs)
            log_debug(f"Consumer thread {thread_id} completed")
        except Exception as e:
            log_error(f"Consumer thread {thread_id} error: {e}", exc_info=True)


from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class WorkUnit:
    type: str  # 'work', 'sentinel', 'result'
    data: Any = None
    producer_id: Optional[int] = None

    @classmethod
    def work_item(cls, data: Any) -> 'WorkUnit':
        return cls(type='work', data=data)

    @classmethod
    def sentinel(cls, producer_id: int) -> 'WorkUnit':
        return cls(type='sentinel', producer_id=producer_id)

    @classmethod
    def result(cls, data: Any) -> 'WorkUnit':
        return cls(type='result', data=data)

    @classmethod
    def batch(cls, data: List[Any]) -> 'WorkUnit':
        return cls(type='batch', data=data)

    def is_work_item(self) -> bool:
        return self.type == 'work'

    def is_sentinel(self) -> bool:
        return self.type == 'sentinel'

    def is_sentinel_for(self, producer_id: int) -> bool:
        return self.is_sentinel() and self.producer_id == producer_id


class BaseProcessor:
    """
    Base class for all processor implementations.

    Provides common functionality and structure for processors that need to
    coordinate between producers and consumers in a thread-safe manner.
    """

    # Class variable for global access to exit processing flag
    exit_processing = False

    def __init__(self, db_ops: DatabaseOperations):
        """
        Initialize the base processor.

        Args:
            db_ops: Database operations instance
        """
        self.db_ops = db_ops
        # Reset class variable for this instance
        BaseProcessor.exit_processing = False
        self.setup_shutdown_handlers()
        self.monitoring_thread = None
        self.monitor_interval = 10.0
        self.monitor_queues = []
        self.monitor_enable = True
        self.total_processed = 0
        self.work_queue = None
        self.result_queue = None
        self.pbar = None
        self.queue_status_display = None
        self.pdc_objects_count = 0
        self.pdc_operations_count = 0
        self.pdc_updates_count = 0
        self.total_objects_saved = 0
        self.last_optimize = 0
        self._profile_seconds = None
        self._profiler = None
        self._profile_timer = None

        # Install SIGUSR1 handler for thread dumps
        setup_thread_dump_handler(self)

    def setup_status_gauges(self, interval: float = 10.0, queues: List[queue.Queue] = None, enable: bool = True):
        """
        Setup status monitoring gauges with optional thread.
        
        Args:
            interval: Update interval in seconds
            queues: List of queues to monitor sizes
            enable: Whether to start monitoring
        """
        self.monitor_interval = interval
        self.monitor_queues = queues or []
        self.monitor_enable = enable
        
        if enable and not self.monitoring_thread:
            self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True, name='Metrics')
            self.monitoring_thread.start()

    def _monitoring_loop(self):
        """Monitoring loop that runs in a daemon thread."""
        while not BaseProcessor.exit_processing:
            self._update_gauges()
            time.sleep(self.monitor_interval)

    def _update_gauges(self):
        """Update and log status gauges."""
        try:
            process = psutil.Process()
            memory_gb = process.memory_info().rss / (1024 ** 3)

            queue_sizes = [q.qsize() for q in self.monitor_queues if hasattr(q, 'qsize')]
            total_queue_size = sum(queue_sizes)

            custom_metrics = self._get_custom_metrics()

            # Filter out None values from custom_metrics to avoid logging issues
            filtered_metrics = {k: v for k, v in custom_metrics.items() if v is not None}
    
            status_msg = "Status Gauges: Memory {:.2f}GB, Queue sizes {} (total: {}), Custom: {}".format(memory_gb, queue_sizes, total_queue_size, filtered_metrics)
            log_info(status_msg)
        except Exception as e:
            log_error(f"Error updating status gauges: {e}")

    def _get_custom_metrics(self) -> Dict[str, Any]:
        """Virtual method for subclass-specific custom metrics."""
        metrics = {}
        # Only include attributes that actually exist on this instance
        if hasattr(self, 'pdc_objects_count'):
            metrics['pdc_objects_count'] = self.pdc_objects_count
        if hasattr(self, 'pdc_operations_count'):
            metrics['pdc_operations_count'] = self.pdc_operations_count
        if hasattr(self, 'pdc_updates_count'):
            metrics['pdc_updates_count'] = self.pdc_updates_count
        return metrics

    def update_pdc_size_gauge(self, context: 'PendingDatabaseContext') -> None:
        """
        Update gauges for PendingDatabaseContext sizes before saving to database.
        This optional hook computes and logs sizes for visibility into context accumulation.
        Also updates instance variables for integration with periodic status gauges.
        """
        if not context:
            objects_count = operations_count = updates_count = 0
        else:
            objects_count = sum(len(lst) for lst in context.objects.values())
            operations_count = len(context.operations)
            updates_count = len(context._updates)

        # Log for immediate visibility before DB write
        log_info(
                  f"PendingDatabaseContext before save_to_database(): "
                  f"objects={objects_count} (total), operations={operations_count}, updates={updates_count}")

        # Update for periodic gauges (shows last batch size; defaults to 0 if no context)
        self.pdc_objects_count = objects_count
        self.pdc_operations_count = operations_count
        self.pdc_updates_count = updates_count


    def _setup_monitoring(self):
        """Optional setup for monitoring - subclasses can override."""
        pass

    def _setup_profiling(self, operation_name: str) -> Tuple[cProfile.Profile, float, threading.Timer]:
        """
        Centralized profiling setup method.

        Args:
            operation_name: Name of the operation being profiled

        Returns:
            Tuple of (profiler, start_time, profile_timer)
        """
        if not global_config.profile_seconds:
            return None, None, None

        self._profile_seconds = global_config.profile_seconds
        self._profiler = cProfile.Profile()
        log_info(f"Starting profiling for {self._profile_seconds} seconds during {operation_name}")
        self._profiler.enable()
        start_time = time.time()
        # Start timer to set exit_processing after specified delay
        self._profile_timer = threading.Timer(self._profile_seconds, self._set_exit_processing)
        self._profile_timer.start()
        return self._profiler, start_time, self._profile_timer

    def _teardown_profiling(self, operation_name: str, start_time: float, work_items_processed: int) -> None:
        """
        Centralized profiling teardown method.

        Args:
            operation_name: Name of the operation being profiled
            start_time: Start time of profiling
            work_items_processed: Number of work items processed
        """
        if not start_time:
            return

        # Cancel timer if still running
        if self._profile_timer and self._profile_timer.is_alive():
            self._profile_timer.cancel()
        self._profiler.disable()
        end_time = time.time()
        execution_time = end_time - start_time
        log_info(f"{operation_name} profiling complete. Time: {execution_time:.2f}s, Work items: {work_items_processed}")
        self._generate_profiling_report(operation_name, execution_time, work_items_processed)

    def _feed_thread(self, work_queue: queue.Queue, max_files: Optional[int], num_producers: int):
        """Abstract method: Feeder thread logic to fetch work items and put sentinels."""
        # Feeder thread: allow reads but not writes
        raise NotImplementedError("Subclasses must implement _feed_thread")

    def _process_work_item(self, data: Any) -> PendingDatabaseContext:
        """Abstract method: Process a single work item into a PendingDatabaseContext."""
        raise NotImplementedError("Subclasses must implement _process_work_item")

    def _process_batch(self, batch: List[Any]) -> PendingDatabaseContext:
        """Abstract method: Process a batch of work items into a PendingDatabaseContext."""
        raise NotImplementedError("Subclasses must implement _process_batch")

    def get_work_count(self, max_files: Optional[int] = None) -> int:
        """Abstract method: Get the total number of work items to process."""
        raise NotImplementedError("Subclasses must implement get_work_count")

    def get_progress_config(self, max_files: Optional[int] = None) -> Tuple[int, str, str]:
        """
        Abstract method: Get progress bar configuration (total, unit, desc).
        Returns:
            Tuple of (total: int, unit: str, desc: str)
        """
        raise NotImplementedError("Subclasses must implement get_progress_config")

    def process_parallel(self, max_files: Optional[int] = None, workers: int = 4) -> int:
        """
        Process work items using the generalized multi-threaded producer-consumer architecture.

        Args:
            max_files: Maximum number of work items to process
            workers: Number of producer threads

        Returns:
            Number of work items processed
        """
        from constants import CURRENT_PROCESSING_VERSION  # If needed by subclass

        # Name the main thread
        threading.current_thread().name = 'Main'

        # Setup profiling if enabled
        self._profiler, start_time, self._profile_timer = self._setup_profiling("process_parallel")

        self.work_queue = queue.Queue(maxsize=10 * BATCH_SIZE)
        self.result_queue = queue.Queue()
        self.queue_status_display = QueueStatusDisplay(self.work_queue, update_interval=30.0, custom_metrics_func=self._get_custom_metrics)
        self.queue_status_display.start()

        # Setup monitoring
        self._setup_monitoring()

        # Setup progress bar
        total, unit, desc = self.get_progress_config(max_files)
        if total == 0:
            # Empty work set is success (e.g. grant_match parallel tier already drained).
            # Do not sys.exit(1) — chains (grant_match → OFAC) must not abort on done.
            log_info(f"No work to do for this step ({desc or 'work'} = 0) — success")
            if self.queue_status_display:
                self.queue_status_display.stop()
            self._teardown_profiling("process_parallel", start_time, 0)
            return 0
        self.pbar = start_progress_reporting(total=total, desc=desc, unit=unit)

        self.total_processed = 0

        # Start feeder thread
        feeder_thread = threading.Thread(
            target=self._feed_thread,
            args=(self.work_queue, max_files, workers)
        )
        feeder_thread.daemon = False
        feeder_thread.start()

        # Start producer threads
        producer_threads = []
        for i in range(workers):
            t = threading.Thread(
                target=self._producer_worker,
                args=(i, workers),
                name=f'Producer-{i+1}'
            )
            t.daemon = False
            t.start()
            producer_threads.append(t)

        # Start consumer thread
        consumer_thread = threading.Thread(
            target=self._consumer_worker,
            args=(workers,),
            name='Consumer'
        )
        consumer_thread.daemon = False
        consumer_thread.start()

        # Setup status gauges
        self.setup_status_gauges(interval=MONITOR_INTERVAL_SECONDS, queues=[self.work_queue])

        # Wait for completion
        log_info("Waiting for feeder thread to complete...")
        feeder_thread.join()
        log_info("Feeder thread completed")

        log_info("Waiting for producer threads to complete...")
        for i, t in enumerate(producer_threads):
            t.join()
            log_info(f"Producer thread {i} completed")
        log_info("All producer threads completed")

        log_info("Waiting for consumer thread to complete...")
        consumer_thread.join()
        log_info("Consumer thread completed")

        # Cleanup
        if self.pbar:
            self.pbar.close()

        if self.queue_status_display:
            self.queue_status_display.stop()

        # Stop profiling if enabled
        self._teardown_profiling("process_parallel", start_time, self.total_processed)

        log_info(f"Processing complete: {self.total_processed} items processed")
        if hasattr(self, 'queue_status_display'):
            self.queue_status_display.stop()
        return self.total_processed

    def _producer_worker(self, producer_id: int, num_producers: int):
        """Producer worker thread: Processes work items from work_queue to result_queue."""
        log_info(f"PRODUCER THREAD {producer_id} STARTED")
        processed_count = 0
        while True:
            # DEADLOCK PREVENTION: Check for exit processing before database operations
            if BaseProcessor.exit_processing:
                log_info("Feeder thread exiting due to exit_processing flag")
                break
            item = self.work_queue.get()

            if item.is_sentinel_for(producer_id):
                self.work_queue.task_done()
                # Send sentinel to result queue
                self.result_queue.put(WorkUnit.sentinel(producer_id))
                log_info(f"Producer {producer_id} processed {processed_count} items, sending sentinel to consumer")
                break
            elif item.is_sentinel():
                # Sentinel for another producer, put back
                self.work_queue.put(item)
                # Do not call task_done() for items that are put back
                time.sleep(0.1)  # Avoid busy waiting
                continue

            if item.type == 'work':
                pdc = self._process_work_item(item.data)
                self.result_queue.put(WorkUnit.result(pdc))
                processed_count += 1
            elif item.type == 'batch':
                pdc = self._process_batch(item.data)
                self.result_queue.put(WorkUnit.result(pdc))
                processed_count += 1

            self.work_queue.task_done()

            # Check for exit processing
            if BaseProcessor.exit_processing:
                break

        log_info(f"PRODUCER THREAD {producer_id} COMPLETED")

    def _consumer_worker(self, num_producers: int):
        """Consumer worker thread: Drains result_queue, batches and executes PDCs with size-based preflight merging."""
        with self.db_ops.acquire_write_conn() as conn:
            current_batch = []
            current_estimated = 0
            sentinels_received = 0
            last_flush_time = time.time()

            def save_current_batch():
                nonlocal current_batch, current_estimated, last_flush_time
                if not current_batch:
                    return

                merged = PendingDatabaseContext.merge(current_batch)
                potential_total = self.total_objects_saved + merged.getTotalObjectCount()
                current_optimize_needed = potential_total // OPTIMIZE_THRESHOLD
                optimize_added = False
                if current_optimize_needed > self.last_optimize:
                    op = DatabaseOperation(DatabaseOperationType.OPTIMIZE_DATABASE, data=None)
                    merged.operations.append(op)
                    optimize_added = True
                    log_info(f"Appending OPTIMIZE_DATABASE to batch after {potential_total} objects")

                log_info(f"Saving batch of {len(current_batch)} contexts to database (estimated_updates: {merged.estimated_updates})")
                self.update_pdc_size_gauge(merged)
                merged.save_to_database(self.db_ops)
                log_info(f"Successfully saved batch of {len(current_batch)} contexts + checkpointed")
                self.total_objects_saved += merged.getTotalObjectCount()
                self.total_processed += len(current_batch)

                current_batch = []
                current_estimated = 0
                last_flush_time = time.time()
                merged = None
                gc.collect()

                if optimize_added:
                    self.last_optimize = current_optimize_needed

            while sentinels_received < num_producers or current_batch:
                try:
                    item = self.result_queue.get(timeout=CONSUMER_POLL_TIMEOUT)
                except queue.Empty:
                    now = time.time()
                    # Time-based flush while producers are still working
                    if current_batch and (now - last_flush_time > CONSUMER_MAX_IDLE_SECONDS):
                        log_info(f"Consumer: time-based flush of {len(current_batch)} contexts (producers still running)")
                        save_current_batch()
                        continue

                    # Final flush when all producers are done
                    if sentinels_received >= num_producers and current_batch:
                        save_current_batch()
                        break

                    continue

                if item.is_sentinel():
                    sentinels_received += 1
                    log_info(f"Received sentinel {sentinels_received}/{num_producers}")
                    self.result_queue.task_done()
                    continue

                context = item.data
                self.result_queue.task_done()

                # Preflight: check if adding this context would exceed the size limit
                if current_estimated + context.estimated_updates > GEOCODING_MAX_UPDATES_PER_BATCH and current_batch:
                    save_current_batch()

                # Add context to current batch
                current_batch.append(context)
                current_estimated += context.estimated_updates

                # Save if batch size reached
                if current_estimated >= CONSUMER_BATCH_SIZE:
                    save_current_batch()

            log_info("CONSUMER THREAD COMPLETED")
    
    def setup_shutdown_handlers(self):
        def signal_handler(signum, frame):
            log_error(f"Received signal {signum}, shutting down gracefully...")
            BaseProcessor.exit_processing = True
            self.handle_shutdown()
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

    def handle_shutdown(self):
        """Perform general shutdown cleanup"""
        self._on_shutdown()

    def _on_shutdown(self):
        """Virtual method for subclass-specific shutdown actions"""
        if self.pbar:
            self.pbar.close()
        if self.queue_status_display:
            self.queue_status_display.stop()

        def merge_pending_contexts(self, contexts: List[PendingDatabaseContext]) -> PendingDatabaseContext:
            """Generalized method to merge multiple PendingDatabaseContext objects into a single context.
            This centralizes the merging logic for efficient batch processing across all database-heavy processors.
            Handles empty and single-context cases directly for optimal performance.
            """
            if not hasattr(self, '_merge_call_count'):
                self._merge_call_count = 0
            self._merge_call_count += 1
            log_info(f"Merge call count: {self._merge_call_count}")
            if not contexts:
                return PendingDatabaseContext()
            if len(contexts) == 1:
                return contexts[0]
            return PendingDatabaseContext.merge(contexts)


class BaseProducer(BaseProcessor):
    """
    Base Producer class for operation collection.

    PRODUCER-CONSUMER PATTERN WARNING:
    This class MUST NOT perform any database writes directly.
    Producers collect DatabaseOperation objects and send them to consumers.
    Only Consumer classes may execute database operations.

    This is a superclass for all *_producer.py classes to provide common functionality.
    """

    def __init__(self, db_ops: DatabaseOperations, batch_size: int = 1000, thread_pool_config: Optional[ThreadPoolConfig] = None):
        super().__init__(db_ops)
        self.batch_size = batch_size
        self._profile_seconds = None
        self._profiler = None
        self.thread_pool_config = thread_pool_config or ThreadPoolConfig()
        self.thread_pool_manager = None
        self._profile_timer = None

    def _set_exit_processing(self):
        """Set exit_processing flag for profiling timeout."""
        print("PROFILING EXIT")
        BaseProcessor.exit_processing = True

    def collect_operations(self) -> List[DatabaseOperation]:
        """
        DEPRECATED: Use collect_contexts() instead for PDC-based processing.
        This method is kept for backward compatibility only.
        """
        # Convert PDC to operations for backward compatibility
        context = self.collect_contexts()
        if not context or context.isEmpty():
            return []

        # Convert context to operations
        return context.save_to_database(self.db_ops)

    def collect_contexts(self) -> 'PendingDatabaseContext':
        """
        Collect PendingDatabaseContext objects for processing.

        This is the preferred method for processors that can use PendingDatabaseContext
        to collect related objects before converting to DatabaseOperation objects.

        Returns:
            List of PendingDatabaseContext objects for the consumer to process
        """
        # Setup profiling if enabled
        self._profiler, start_time, self._profile_timer = self._setup_profiling("collect_contexts")

        # Setup progress bar
        progress_scope = self.get_progress_scope(bytes=global_config.progress == "bytes")
        total = progress_scope.get("total", 0)
        unit = progress_scope.get("unit", "items")
        start_progress_reporting(total=total, desc="Collecting contexts", unit=unit)

        # Create a single master context to accumulate all work
        from pending_database_context import PendingDatabaseContext
        master_context = PendingDatabaseContext()

        offset = 0
        work_items_processed = 0

        log_info(f"Starting to collect contexts (batch_size={self.batch_size})")

        last_pk = None
        while True:
            # Get next batch of work items using key-value paging
            batch, new_last_pk = self._get_work_batch(last_pk)

            if BaseProcessor.exit_processing:
                print("Exiting thread")
                break

            if not batch:
                # No more work to process
                break

            # Process this batch into a single context
            context = self._process_work_batch_to_context(batch)
            if self.exit_processing:
                print("Exiting thread")
                break
            if context:
                master_context = self.merge_pending_contexts([master_context, context])

            # Count work items processed (each batch represents one work item)
            work_items_processed += len(batch)

            # Update last_pk for next batch
            last_pk = new_last_pk

            # Check if we've reached the global limit
            if global_config.max_files and work_items_processed >= global_config.max_files:
                log_info(f"Reached max_files limit: {global_config.max_files} work items")
                break

            # Check for exit processing
            if BaseProcessor.exit_processing:
                print("Exiting thread")
                break

            # Log progress
            if work_items_processed % 100 == 0:
                log_info(f"Collected contexts for {work_items_processed} work items so far")

        # Stop profiling if enabled
        self._teardown_profiling("collect_contexts", start_time, work_items_processed)

        log_info(f"Collected master context with {work_items_processed} work items")
        return master_context

    def _process_work_batch_to_context(self, batch) -> Optional['PendingDatabaseContext']:
        """
        Process a batch of work items into a single PendingDatabaseContext object.

        This method should be overridden by subclasses that want to use
        PendingDatabaseContext instead of direct DatabaseOperation objects.

        Args:
            batch: Batch of work items to process

        Returns:
            Single PendingDatabaseContext object, or None if no work was processed
        """
        # Default implementation - subclasses should override this
        raise NotImplementedError("Subclasses using PendingDatabaseContext must implement _process_work_batch_to_context")


    def collect_contexts_parallel(self, max_workers: int = None) -> 'PendingDatabaseContext':
        """
        Collect contexts using thread pool for parallel processing.

        Args:
            max_workers: Maximum number of producer threads (overrides config)

        Returns:
            List of PendingDatabaseContext objects for the consumer to execute
        """
        # Setup profiling if enabled
        self._profiler, start_time, self._profile_timer = self._setup_profiling("collect_contexts_parallel")

        # Initialize thread pool manager
        self.thread_pool_manager = ThreadPoolManager(self.thread_pool_config, self)

        # Override max_workers if specified
        if max_workers is not None:
            self.thread_pool_config.producer_config.max_workers = max_workers

        # Create a single master context to accumulate all work
        from pending_database_context import PendingDatabaseContext
        master_context = PendingDatabaseContext()

        work_items_processed = 0

        log_info(f"Starting parallel context collection (max_workers={self.thread_pool_config.producer_config.max_workers})")

        try:
            # Get all work items first (for parallel distribution) using key-value paging
            all_work_items = []
            last_pk = None
            while True:
                batch, new_last_pk = self._get_work_batch(last_pk)
                if not batch:
                    break
                all_work_items.extend(batch)

                # Update last_pk for next batch
                last_pk = new_last_pk

                # Check global limit
                if global_config.max_files and len(all_work_items) >= global_config.max_files:
                    all_work_items = all_work_items[:global_config.max_files]
                    break

            if not all_work_items:
                return master_context

            # Start producer pool
            self.thread_pool_manager.start_producer_pool(
                all_work_items,
                self._parallel_work_batch_processor
            )

            # Collect results from result queue and merge into master context
            sentinels_received = 0
            num_producers = len(self.thread_pool_manager.producer_threads)
            while sentinels_received < num_producers:
                if BaseProcessor.exit_processing:
                    self.thread_pool_manager.shutdown()
                    print("Exiting thread")
                    break
                try:
                    result = self.thread_pool_manager.result_queue.get(timeout=1.0)
                    if BaseProcessor.exit_processing:
                        self.thread_pool_manager.result_queue.task_done()
                        break
                    if result is None:  # Sentinel
                        sentinels_received += 1
                    elif isinstance(result, PendingDatabaseContext):
                        # Each result is a context from one producer
                        # Merge into the master context
                        master_context = self.merge_pending_contexts([master_context, result])
                        work_items_processed += 1  # Each result represents work from one producer
                    self.thread_pool_manager.result_queue.task_done()
                    if BaseProcessor.exit_processing:
                        print("Exiting thread")
                        break
                except queue.Empty:
                    if BaseProcessor.exit_processing:
                        print("Exiting thread")
                        break
                    continue

            # Wait for completion
            self.thread_pool_manager.wait_for_completion()

        finally:
            # Stop profiling if enabled
            self._teardown_profiling("collect_contexts_parallel", start_time, work_items_processed)

            # Cleanup
            if self.thread_pool_manager:
                self.thread_pool_manager.shutdown()

        log_info(f"Collected master context with {work_items_processed} work items (parallel)")
        return master_context

    def _parallel_work_batch_processor(self, work_items: List[Any], work_queue: queue.Queue,
                                        result_queue: queue.Queue, thread_id: int, num_threads: int) -> None:
        """
        Process work items in parallel using thread pool.

        Args:
            work_items: List of work items to process
            work_queue: Queue for intermediate work (not used in this implementation)
            result_queue: Queue to put results
            thread_id: ID of this thread
            num_threads: Total number of threads
        """
        try:
            # Create a single context for this thread's work
            from pending_database_context import PendingDatabaseContext
            thread_context = PendingDatabaseContext()

            # Distribute work items among threads
            for i in range(thread_id, len(work_items), num_threads):
                if BaseProcessor.exit_processing:
                    break

                work_item = work_items[i]

                # Process single work item into context and merge into thread context
                context = self._process_work_batch_to_context([work_item])
                if BaseProcessor.exit_processing:
                    print("Exiting thread")
                    break
                if context:
                    thread_context = PendingDatabaseContext.merge([thread_context, context])

                # Log progress
                if (i + 1) % 50 == 0:
                    log_info(f"Producer {thread_id}: processed {i + 1}/{len(work_items)} work items")

            # Put the single merged context in result queue
            result_queue.put(thread_context)

        except Exception as e:
            log_error(f"Parallel work processor {thread_id} error: {e}", exc_info=True)
        finally:
            # Signal completion
            result_queue.put(None)


    def _get_work_batch(self, last_pk: Optional[Any] = None) -> Tuple[List[Any], Optional[Any]]:
        """Get a batch of work items using key-value paging - to be implemented by subclasses.
        
        Args:
            last_pk: The last primary key from the previous batch (None for first batch)
        
        Returns:
            Tuple of (batch: List of work items, max_pk: The maximum primary key in this batch or None if empty)
        """
        raise NotImplementedError("Subclasses must implement _get_work_batch")

    def _process_work_batch(self, batch: List[Any]) -> List[DatabaseOperation]:
        """DEPRECATED: Use _process_work_batch_to_context instead for PDC-based processing"""
        # Convert PDC to operations for backward compatibility
        context = self._process_work_batch_to_context(batch)
        if not context or context.isEmpty():
            return []
        return context.save_to_database(self.db_ops)

    def get_progress_scope(self, bytes: bool = False) -> Dict[str, Any]:
        """Get the scope of work for progress bar setup - to be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement get_progress_scope")


    def _generate_profiling_report(self, operation_name: str, execution_time: float, work_items_processed: int):
        """
        Generate profiling report files similar to profile_pipeline.py examples.
        """
        if not self._profiler:
            return

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
        ps = pstats.Stats(self._profiler, stream=s).sort_stats('cumulative')
        ps.print_stats(50)  # Top 50 functions by cumulative time
        profiling_output = s.getvalue()

        # Calculate metrics
        processing_rate = work_items_processed / execution_time if execution_time > 0 else 0
        throughput = work_items_processed / execution_time * 60  # items per minute

        # Save stats file
        self._profiler.dump_stats(stats_filename)

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


class ProcessorCoordinator:
    """
    Coordinator for processor operations using producer-consumer pattern.

    This class provides a standardized way to coordinate any processor that follows
    the collect operations → bulk execute pattern. It centralizes the threading logic
    and ensures all processors work consistently.
    """

    def __init__(self, db_ops: DatabaseOperations):
        self.db_ops = db_ops

    def process_with_producer_consumer(self, producer: 'BaseProducer', consumer: 'BaseConsumer',
                                       max_files: Optional[int] = None, workers: int = 4) -> int:
        """
        Process using producer-consumer pattern with standardized coordination.

        Args:
            producer: Producer instance that collects operations
            consumer: Consumer instance that executes operations
            max_files: Maximum number of files/items to process
            workers: Number of worker threads for parallel processing

        Returns:
            Number of items processed
        """
        # Set global max_files limit if specified
        if max_files is not None:
            global_config.max_files = max_files

        # Collect context using producer
        context = producer.collect_contexts_parallel(max_workers=workers)

        if not context or context.isEmpty():
            log_info("No context to process")
            return 0

        # Execute context using consumer
        processed_count = consumer.execute_contexts_batch(context)

        log_info(f"Processing complete: {processed_count} objects inserted")
        return processed_count


def dump_threads_handler(signum, frame):
    """Signal handler: Dumps formatted stack traces for all live threads."""
    try:
        import os
        frames = sys._current_frames()

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Stack traces for {len(frames)} threads (PID: {os.getpid()})", file=sys.stderr)
        print(f"Time: {time.ctime()}", file=sys.stderr)
        print(f"Signal: {signum} (USR1)", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)

        # Get all live threads once for name lookup
        live_threads = {t.ident: t for t in threading.enumerate() if t.is_alive()}

        for thread_id, frame in frames.items():
            # Use the real thread.name if available
            thread_obj = live_threads.get(thread_id)
            thread_name = thread_obj.name if thread_obj else f"Thread-{thread_id} (unknown)"
            daemon = thread_obj.daemon if thread_obj else "unknown"
            
            print(f"Thread: {thread_name} (ident: 0x{thread_id:x}, daemon: {daemon})", file=sys.stderr)

            # Stack trace
            stack_lines = traceback.format_stack(frame)
            print("".join(stack_lines), file=sys.stderr)

        print(f"{'='*60}\n", file=sys.stderr)
        print("Thread dump complete. Process continuing...", file=sys.stderr)
        sys.stderr.flush()
    except Exception as e:
        print(f"Error in thread dump: {e}", file=sys.stderr)
        sys.stderr.flush()


def exit_signal_handler(processor):
    """Signal handler to set exit_processing flag on SIGINT/SIGTERM"""
    def handler(signum, frame):
        log_error(f"Received signal {signum}, shutting down gracefully...")
        processor.exit_processing = True
        processor.handle_shutdown()
    return handler


def setup_thread_dump_handler(processor):
    """Setup signal handlers for thread dumps and exit processing"""
    try:
        import signal
        signal.signal(signal.SIGUSR1, dump_threads_handler)
    except (OSError, ValueError):
        # Signal not available on this platform
        pass


class BaseConsumer(BaseProcessor):
    """
    Base Consumer class for database operations execution.

    PRODUCER-CONSUMER PATTERN WARNING:
    This class is responsible for executing database operations.
    Only consumers may perform database writes. Producers must never write the database.

    This is a superclass for all *_consumer.py classes to provide common functionality.
    """

    def __init__(self, db_ops: DatabaseOperations, thread_pool_config: Optional[ThreadPoolConfig] = None):
        super().__init__(db_ops)
        self._profile_seconds = None
        self._profiler = None
        self.thread_pool_config = thread_pool_config or ThreadPoolConfig()
        self.thread_pool_manager = None

    def execute_operations_batch(self, operations: List[DatabaseOperation], progress_callback=None) -> int:
        """
        DEPRECATED: Use execute_contexts_batch instead for PDC-based processing.

        Execute a batch of database operations.

        Args:
            operations: List of DatabaseOperation objects to execute
            progress_callback: Optional callback for progress updates

        Returns:
            Number of operations processed
        """
        # Convert operations to PDC and execute
        from pending_database_context import PendingDatabaseContext
        context = PendingDatabaseContext()

        # Add all operations to context
        for operation in operations:
            context.addOperationToDatabase(operation)

        return self.execute_contexts_batch(context, progress_callback)

    def execute_contexts_batch(self, context: 'PendingDatabaseContext', progress_callback=None) -> int:
        """
        Execute a PendingDatabaseContext object.

        This method executes all operations directly. PDC handles all operation execution internally.

        Args:
            context: PendingDatabaseContext object to execute
            progress_callback: Optional callback for progress updates

        Returns:
            Total number of objects inserted
        """
        if not context:
            return 0

        self.update_pdc_size_gauge(context)

        # Execute the context (handles all operations)
        ids = context.save_to_database(self.db_ops)

        return len(ids) if ids else 0

    def _execute_tail_operations(self, operations_by_type, processed_count):
        """Execute tail operations (optimize and progress updates)"""
        # Handle OPTIMIZE_DATABASE operations next to last, then progress bar
        if DatabaseOperationType.OPTIMIZE_DATABASE.value in operations_by_type:
            for operation in operations_by_type[DatabaseOperationType.OPTIMIZE_DATABASE.value]:
                self._execute_optimize_operation(operation)
                processed_count += 1

        progress_operations = 0
        if DatabaseOperationType.PROGRESS_UPDATE.value in operations_by_type:
            progress_operations = len(operations_by_type[DatabaseOperationType.PROGRESS_UPDATE.value])
            for operation in operations_by_type[DatabaseOperationType.PROGRESS_UPDATE.value]:
                from logging_utils import update_progress
                progress_count = operation.data.get("count", 0)
                log_debug(f"DEBUG: Processing PROGRESS_UPDATE operation with count={progress_count}")
                update_progress(n=progress_count)  # Use global progress bar
                processed_count += 1
        return processed_count

    def _execute_optimize_operation(self, operation):
        """Execute database optimization operation"""
        if operation.operation_type != DatabaseOperationType.OPTIMIZE_DATABASE:
            return

        log_info("Starting database optimization...")
        try:
            # Call the optimize_database method from DatabaseOperations
            self.db_ops.optimize_database()
            log_info("Database optimization completed successfully")
        except Exception as e:
            log_error(f"Database optimization failed: {e}", exc_info=True)
            raise

    def _execute_progress_update_operation(self, operation):
        """Execute progress update operation"""
        if operation.operation_type != DatabaseOperationType.PROGRESS_UPDATE:
            return

        from logging_utils import update_progress
        progress_count = operation.data.get("count", 0)
        log_debug(f"DEBUG: Processing PROGRESS_UPDATE operation with count={progress_count}")
        update_progress(n=progress_count)
    
    def execute_operations_parallel(self, operations: List[DatabaseOperation], progress_callback=None) -> int:
        """DEPRECATED: Use PDC-based parallel execution instead"""
        # Convert operations to PDC and execute
        from pending_database_context import PendingDatabaseContext
        context = PendingDatabaseContext()

        # Add all operations to context
        for operation in operations:
            context.addOperationToDatabase(operation)

        return self.execute_contexts_batch(context, progress_callback)

    def _parallel_operations_processor(self, work_queue: queue.Queue, result_queue: queue.Queue,
                                       thread_id: int, num_producers: int, operations: List[DatabaseOperation],
                                       progress_callback=None) -> None:
        """DEPRECATED: Use PDC-based parallel processing instead"""
        # Convert operations to PDC and execute
        from pending_database_context import PendingDatabaseContext
        context = PendingDatabaseContext()

        # Add all operations to context
        for operation in operations:
            context.addOperationToDatabase(operation)

        processed = self.execute_contexts_batch(context, progress_callback)
        result_queue.put(processed)
        result_queue.put(None)  # Signal completion

    def _process_batch_operations(self, operations: List[DatabaseOperation], progress_callback=None) -> int:
        """DEPRECATED: Use PDC-based batch processing instead"""
        # Convert operations to PDC and execute
        from pending_database_context import PendingDatabaseContext
        context = PendingDatabaseContext()

        # Add all operations to context
        for operation in operations:
            context.addOperationToDatabase(operation)

        return self.execute_contexts_batch(context, progress_callback)

    def _execute_operations_batch_with_profiling(self, operations: List[DatabaseOperation], progress_callback=None) -> int:
        """DEPRECATED: Use PDC-based profiling instead"""
        # Convert operations to PDC and execute
        from pending_database_context import PendingDatabaseContext
        context = PendingDatabaseContext()

        # Add all operations to context
        for operation in operations:
            context.addOperationToDatabase(operation)

        return self.execute_contexts_batch(context, progress_callback)

    def _process_operations_batch(self, operations_by_type):
        """DEPRECATED: Use PDC-based processing instead"""
        # Convert operations to PDC and execute
        from pending_database_context import PendingDatabaseContext
        context = PendingDatabaseContext()

        # Add all operations to context
        for op_list in operations_by_type.values():
            for operation in op_list:
                context.addOperationToDatabase(operation)

        return self.execute_contexts_batch(context)