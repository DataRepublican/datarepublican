#!/usr/bin/env python3
"""
backfill_charities_processor.py - Processor for creating backfill stubs for unmatched grant EINs
"""

from typing import List, Dict, Any, Tuple, Optional
import queue
from database_operations import DatabaseOperations, DatabaseOperationType
from logging_utils import log_info, log_debug
from config import global_config
from base_processor import BaseProcessor, WorkUnit
from pending_database_context import PendingDatabaseContext
from models.backfill import Backfill


class BackfillCharitiesProcessor(BaseProcessor):
    """Processor for creating backfill charity stubs"""

    def __init__(self, db_ops: DatabaseOperations):
        super().__init__(db_ops)
        self.batch_size = 1000

    def backfill_charities(self) -> int:
        """Run the backfill process"""
        return self.process_parallel(global_config.max_files, global_config.workers)

    def get_work_count(self, max_files: Optional[int] = None) -> int:
        query = """
        SELECT COUNT(DISTINCT recipient_ein)
        FROM Grants
        WHERE recipient_ein IS NOT NULL
        AND recipient_ein NOT IN (SELECT ein FROM Charities)
        """
        result = self.db_ops.execute_query(query)
        total = result.fetchone()[0]
        if max_files:
            total = min(total, max_files)
        return total

    def get_progress_config(self, max_files: Optional[int] = None) -> Tuple[int, str, str]:
        total = self.get_work_count(max_files)
        return total, 'eins', 'Backfilling charity stubs'

    def _feed_thread(self, work_queue: queue.Queue, max_files: Optional[int], num_producers: int):
        last_id = None
        enqueued = 0
        while True:
            if self.exit_processing:
                break
            batch, new_last = self._get_work_batch(last_id)
            if not batch:
                break
            work_queue.put(WorkUnit.batch(batch))
            enqueued += len(batch)
            last_id = new_last
            if max_files and enqueued >= max_files:
                break
        for i in range(num_producers):
            work_queue.put(WorkUnit.sentinel(i))

    def _get_work_batch(self, last_id: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        query = """
        SELECT recipient_ein, ANY_VALUE(grantee_name) as name, ANY_VALUE(colocator) as colocator,
               SUBSTR(ANY_VALUE(colocator), STRPOS(ANY_VALUE(colocator), ':') + 1) as zip_code,
               MIN(grant_id) as min_id
        FROM Grants
        WHERE recipient_ein IS NOT NULL
        AND recipient_ein NOT IN (SELECT ein FROM Charities)
        GROUP BY recipient_ein
        """
        params: Tuple = (self.batch_size,)
        if last_id:
            query += " HAVING min_id > ?"
            params = (last_id,) + params
        query += " ORDER BY min_id LIMIT ?"
        rows = self.db_ops.execute_query(query, params).fetchall()
        batch = [dict(zip(['recipient_ein', 'name', 'colocator', 'zip_code', 'min_id'], row)) for row in rows]
        new_last = rows[-1][4] if rows else None
        return batch, new_last

    def _process_batch(self, batch: List[Dict[str, Any]]) -> PendingDatabaseContext:
        context = PendingDatabaseContext()
        for item in batch:
            backfill = Backfill(
                recipient_ein=item['recipient_ein'],
                name=item['name'],
                colocator=item['colocator'],
                zip_code=item['zip_code'],
                source='backfill'
            )
            context.addObjectToDatabase(backfill)
        progress_op = DatabaseOperation(
            DatabaseOperationType.PROGRESS_UPDATE,
            data={"count": len(batch)}
        )
        context.addOperationToDatabase(progress_op)
        return context