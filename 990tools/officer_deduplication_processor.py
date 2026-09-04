#!/usr/bin/env python3
"""
officer_deduplication_processor.py - Officer deduplication for IRS 990 data processing

This module handles deduplication of officers across different charities and tax years,
creating master-child relationships similar to address deduplication.

Refactored to use producer-consumer pattern with ThreadPoolManager for parallel processing.
"""

import uuid
from typing import List, Tuple, Dict, Set, Any, Optional
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from base_processor import BaseProducer, BaseConsumer, ThreadPoolManager, ThreadPoolConfig, PoolConfig
from logging_utils import log_info, log_error, log_debug, log_warning


class OfficerDeduplicationProducer(BaseProducer):
    """Producer for officer deduplication operations"""

    def __init__(self, db_ops: DatabaseOperations, batch_size: int = 1000):
        super().__init__(db_ops, batch_size)

    def _get_work_batch(self, offset: int) -> List[Dict[str, Any]]:
        """Get batch of duplicate officer groups for processing"""
        # Find duplicate officers by name
        query = """
            SELECT
                LOWER(TRIM(o.first_name)) || '|' || LOWER(TRIM(o.last_name)) || '|' || LOWER(TRIM(c.filer_name)) as name_key,
                LIST(o.officer_id) as officer_ids
            FROM Officers o
            JOIN Charities c ON o.charity_id = c.charity_id
            WHERE o.master_id IS NULL
            GROUP BY LOWER(TRIM(o.first_name)) || '|' || LOWER(TRIM(o.last_name)) || '|' || LOWER(TRIM(c.filer_name))
            HAVING COUNT(*) > 1
            ORDER BY name_key
            LIMIT ? OFFSET ?
        """

        result = self.db_ops.execute_query(query, (self.batch_size, offset))
        rows = result.fetchall() if result else []

        work_items = []
        for row in rows:
            name_key = row[0]
            officer_ids = [str(oid) for oid in row[1]] if row[1] else []
            if len(officer_ids) > 1:
                work_items.append({
                    'name_key': name_key,
                    'officer_ids': officer_ids
                })

        return work_items

    def get_progress_scope(self, bytes: bool = False) -> Dict[str, Any]:
        """Estimate total officers needing deduplication and return appropriate unit"""
        # Estimate total duplicate officers by summing counts from duplicate groups
        query = """
            SELECT SUM(group_count) as total_officers FROM (
                SELECT COUNT(*) as group_count
                FROM Officers o
                JOIN Charities c ON o.charity_id = c.charity_id
                WHERE o.master_id IS NULL
                GROUP BY LOWER(TRIM(o.first_name)) || '|' || LOWER(TRIM(o.last_name)) || '|' || LOWER(TRIM(c.filer_name))
                HAVING COUNT(*) > 1
            )
        """

        result = self.db_ops.execute_query(query)
        total = 0
        if result:
            row = result.fetchone()
            if row and row[0]:
                total = row[0]

        unit = "bytes" if bytes else "officers"
        return {"total": total, "unit": unit}

    def _process_work_batch(self, batch: List[Dict[str, Any]]) -> List[DatabaseOperation]:
        """Process batch of duplicate officer groups into deduplication operations"""
        operations = []

        for duplicate_group in batch:
            name_key = duplicate_group['name_key']
            officer_ids = duplicate_group['officer_ids']

            # Create master officer operation
            master_id = str(uuid.uuid4())
            operations.append(DatabaseOperation(
                DatabaseOperationType.GENERIC_UPDATE,
                {
                    'operation': 'create_master_officer',
                    'master_id': master_id,
                    'officer_id': officer_ids[0]  # First officer becomes master
                }
            ))

            # Create child officer update operations
            for child_id in officer_ids[1:]:
                operations.append(DatabaseOperation(
                    DatabaseOperationType.GENERIC_UPDATE,
                    {
                        'operation': 'update_child_officer',
                        'master_id': master_id,
                        'officer_id': child_id
                    }
                ))

        return operations


class OfficerDeduplicationConsumer(BaseConsumer):
    """Consumer for officer deduplication operations"""

    def __init__(self, db_ops: DatabaseOperations):
        super().__init__(db_ops)

    def _process_operations_batch(self, operations_by_type: Dict[str, List[DatabaseOperation]]) -> int:
        """Process officer deduplication operations"""
        processed_count = 0

        if DatabaseOperationType.GENERIC_UPDATE.value in operations_by_type:
            generic_ops = operations_by_type[DatabaseOperationType.GENERIC_UPDATE.value]

            # Group operations by type
            create_master_ops = []
            update_child_ops = []

            for op in generic_ops:
                data = op.data
                if data.get('operation') == 'create_master_officer':
                    create_master_ops.append(data)
                elif data.get('operation') == 'update_child_officer':
                    update_child_ops.append(data)

            # Process master creation operations
            if create_master_ops:
                processed_count += self._process_create_master_operations(create_master_ops)

            # Process child update operations
            if update_child_ops:
                processed_count += self._process_update_child_operations(update_child_ops)

        return processed_count

    def _process_create_master_operations(self, operations: List[Dict[str, Any]]) -> int:
        """Process master officer creation operations"""
        if not operations:
            return 0

        # Prepare bulk update data
        updates = []
        for op in operations:
            updates.append({
                'officer_id': op['officer_id'],
                'master_id': op['master_id']
            })

        # Bulk update master officers
        count = self.db_ops.bulk_update('Officers', updates, 'officer_id')
        log_debug(f"Created {count} master officers")
        return count

    def _process_update_child_operations(self, operations: List[Dict[str, Any]]) -> int:
        """Process child officer update operations"""
        if not operations:
            return 0

        # Prepare bulk update data
        updates = []
        for op in operations:
            updates.append({
                'officer_id': op['officer_id'],
                'master_id': op['master_id']
            })

        # Bulk update child officers
        count = self.db_ops.bulk_update('Officers', updates, 'officer_id')
        log_debug(f"Updated {count} child officers")
        return count


class OfficerDeduplicationProcessor:
    """Handles officer deduplication and master-child relationship creation using producer-consumer pattern"""

    def __init__(self, db_ops: DatabaseOperations, thread_pool_config: Optional[ThreadPoolConfig] = None):
        self.db_ops = db_ops
        self.thread_pool_config = thread_pool_config or ThreadPoolConfig(
            producer_config=PoolConfig(max_workers=2, batch_size=1000),
            consumer_config=PoolConfig(max_workers=1, batch_size=1000)  # Single consumer for DB safety
        )

    def deduplicate_officers(self) -> int:
        """Deduplicate officers and create master-child relationships using producer-consumer pattern"""
        log_info("Starting officer deduplication with producer-consumer pattern")

        # Initialize producer and consumer
        producer = OfficerDeduplicationProducer(self.db_ops)
        consumer = OfficerDeduplicationConsumer(self.db_ops)

        # Initialize thread pool manager
        thread_pool_manager = ThreadPoolManager(self.thread_pool_config)

        total_processed = 0

        try:
            # Start consumer pool
            thread_pool_manager.start_consumer_pool(
                self._consumer_wrapper,
                len(thread_pool_manager.producer_threads),
                consumer,
                progress_callback=self._progress_callback
            )

            # Collect operations using producer
            operations = producer.collect_operations()

            if not operations:
                log_info("No duplicate officers found")
                return 0

            log_info(f"Collected {len(operations)} deduplication operations")

            # Put operations in work queue for consumer
            for operation in operations:
                thread_pool_manager.work_queue.put(operation)

            # Signal end of work
            thread_pool_manager.work_queue.put(None)

            # Wait for completion
            thread_pool_manager.wait_for_completion()

            # Collect results
            while not thread_pool_manager.result_queue.empty():
                try:
                    result = thread_pool_manager.result_queue.get_nowait()
                    if isinstance(result, int):
                        total_processed += result
                    thread_pool_manager.result_queue.task_done()
                except:
                    break

        finally:
            # Cleanup
            thread_pool_manager.shutdown()

        log_info(f"Officer deduplication complete. Processed {total_processed} officer records.")
        return total_processed

    def _consumer_wrapper(self, result_queue, thread_id: int, num_producers: int, consumer, progress_callback=None):
        """Wrapper for consumer thread execution"""
        try:
            log_debug(f"Consumer thread {thread_id} starting")
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
                        processed = consumer.execute_operations_batch([operation])
                        if progress_callback:
                            progress_callback(processed)

                    result_queue.task_done()

                except:
                    if hasattr(self, 'thread_pool_manager') and self.thread_pool_manager and self.thread_pool_manager.shutdown_event.is_set():
                        break
                    continue

        except Exception as e:
            log_error(f"Consumer thread {thread_id} error: {e}", exc_info=True)

    def _progress_callback(self, count: int):
        """Progress callback for consumer operations"""
        log_debug(f"Processed {count} officer deduplication operations")
