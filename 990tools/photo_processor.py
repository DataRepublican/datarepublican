#!/usr/bin/env python3
"""
photo_processor.py - Google Knowledge Graph API integration for officer photos

This module handles fetching officer photos using the Google Knowledge Graph API,
with throttling, caching, and proper error handling. Uses producer-consumer pattern
with ThreadPoolManager for concurrent processing.
"""

import os
import json
import time
import requests
import hashlib
from typing import Optional, Dict, List, Any
from pathlib import Path

from logging_utils import log_info, log_error, log_debug, log_warning
from config import global_config
from base_processor import BaseProducer, BaseConsumer, ThreadPoolManager, ThreadPoolConfig, PoolConfig
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType


class PhotoProducer(BaseProducer):
    """Producer for collecting officer photo processing operations"""

    def __init__(self, db_ops: DatabaseOperations, cache_dir: Optional[str] = None,
                 thread_pool_config: Optional[ThreadPoolConfig] = None):
        super().__init__(db_ops, thread_pool_config=thread_pool_config)
        self.cache_dir = cache_dir or os.path.join(global_config.final_dir, "photo_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.api_key = os.getenv('GOOGLE_KNOWLEDGE_GRAPH_API_KEY')

    def _get_work_batch(self, offset: int) -> List[Dict[str, Any]]:
        """Get batch of officers needing photo processing"""
        if not self.api_key:
            return []

        # Get unique officers (master records only) without photos
        query = """
            SELECT o.officer_id, o.first_name, o.last_name, c.filer_name
            FROM Officers o
            JOIN Charities c ON o.charity_id = c.charity_id
            WHERE o.master_id IS NULL
            AND (o.photo_url IS NULL OR o.photo_url = '')
            AND o.first_name IS NOT NULL AND o.last_name IS NOT NULL
            ORDER BY o.last_name, o.first_name
            LIMIT ? OFFSET ?
        """

        officers = self.db_ops.execute_query(query, (self.batch_size, offset)).fetchall()
        return [
            {
                'officer_id': officer_id,
                'first_name': first_name,
                'last_name': last_name,
                'charity_name': charity_name
            }
            for officer_id, first_name, last_name, charity_name in officers
        ]

    def _process_work_batch(self, batch: List[Dict[str, Any]]) -> List[DatabaseOperation]:
        """Process batch of officers into photo search operations"""
        operations = []

        for officer_data in batch:
            officer_id = officer_data['officer_id']
            first_name = officer_data['first_name']
            last_name = officer_data['last_name']
            charity_name = officer_data['charity_name']

            # Create search query
            full_name = f"{first_name} {last_name}".strip()
            search_query = f"{full_name} {charity_name}" if charity_name else full_name

            # Create operation for photo search
            operation_data = {
                'officer_id': officer_id,
                'search_query': search_query,
                'cache_dir': self.cache_dir,
                'api_key': self.api_key
            }

            operations.append(DatabaseOperation(
                operation_type=DatabaseOperationType.GENERIC_UPDATE,
                data={**operation_data, 'operation_name': "search_officer_photo"}
            ))

        return operations

    def get_progress_scope(self, bytes=False):
        """Estimate total officers needing photos and return appropriate unit"""
        query = """
            SELECT COUNT(*) FROM Officers o
            JOIN Charities c ON o.charity_id = c.charity_id
            WHERE o.master_id IS NULL
            AND (o.photo_url IS NULL OR o.photo_url = '')
            AND o.first_name IS NOT NULL AND o.last_name IS NOT NULL
        """
        result = self.db_ops.execute_query(query).fetchone()
        count = result[0] if result else 0

        if bytes:
            # Estimate total bytes assuming average photo size of 50KB
            total = count * 50000
            unit = "bytes"
        else:
            total = count
            unit = "officers"

        return {"total": total, "unit": unit}


class PhotoConsumer(BaseConsumer):
    """Consumer for executing photo processing operations"""

    def __init__(self, db_ops: DatabaseOperations, thread_pool_config: Optional[ThreadPoolConfig] = None):
        super().__init__(db_ops, thread_pool_config=thread_pool_config)
        self.api_key = os.getenv('GOOGLE_KNOWLEDGE_GRAPH_API_KEY')
        self.last_request_time = 0
        self.min_request_interval = 1.0

    def _rate_limit(self):
        """Enforce rate limiting"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _get_cache_key(self, name: str) -> str:
        """Generate cache key for a name"""
        return hashlib.md5(name.lower().encode()).hexdigest()

    def _load_cache(self, cache_dir: str, cache_key: str) -> Optional[Dict]:
        """Load cached API response"""
        cache_file = os.path.join(cache_dir, f"{cache_key}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log_debug(f"Failed to load cache for {cache_key}: {e}")
        return None

    def _save_cache(self, cache_dir: str, cache_key: str, data: Dict):
        """Save API response to cache"""
        cache_file = os.path.join(cache_dir, f"{cache_key}.json")
        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log_warning(f"Failed to save cache for {cache_key}: {e}")

    def _search_knowledge_graph(self, name: str, cache_dir: str) -> Optional[str]:
        """Search Google Knowledge Graph for a person's photo"""
        if not self.api_key:
            return None

        # Rate limit
        self._rate_limit()

        # Check cache first
        cache_key = self._get_cache_key(name)
        cached_result = self._load_cache(cache_dir, cache_key)
        if cached_result:
            log_debug(f"Using cached result for {name}")
            return cached_result.get('photo_url')

        # Make API request
        url = "https://kgsearch.googleapis.com/v1/entities:search"
        params = {
            'query': name,
            'key': self.api_key,
            'limit': 1,
            'types': 'Person'
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            cache_data = {'photo_url': None, 'timestamp': time.time()}

            if 'itemListElement' in data and data['itemListElement']:
                entity = data['itemListElement'][0].get('result', {})
                if 'image' in entity and 'contentUrl' in entity['image']:
                    photo_url = entity['image']['contentUrl']
                    cache_data['photo_url'] = photo_url
                    log_debug(f"Found photo for {name}: {photo_url}")

            # Cache the result
            self._save_cache(cache_dir, cache_key, cache_data)
            return cache_data['photo_url']

        except requests.RequestException as e:
            log_warning(f"API request failed for {name}: {e}")
            # Cache empty result to avoid repeated failures
            self._save_cache(cache_dir, cache_key, {'photo_url': None, 'timestamp': time.time(), 'error': str(e)})
            return None
        except Exception as e:
            log_error(f"Unexpected error searching for {name}: {e}")
            return None

    def _process_operations_batch(self, operations_by_type: Dict[str, List[DatabaseOperation]]) -> int:
        """Process photo search operations"""
        processed_count = 0

        # Handle custom photo search operations
        if 'generic_update' in operations_by_type:
            for operation in operations_by_type['generic_update']:
                if operation.data.get('operation_name') == "search_officer_photo":
                    data = operation.data
                    officer_id = data['officer_id']
                    search_query = data['search_query']
                    cache_dir = data['cache_dir']

                    # Search for photo
                    photo_url = self._search_knowledge_graph(search_query, cache_dir)

                    if photo_url:
                        # Update master officer
                        update_query = """
                            UPDATE Officers
                            SET photo_url = ?
                            WHERE officer_id = ?
                        """
                        self.db_ops.execute_query(update_query, (photo_url, officer_id))

                        # Also update all child officers with the same photo
                        update_children_query = """
                            UPDATE Officers
                            SET photo_url = ?
                            WHERE master_id = (
                                SELECT master_id FROM Officers WHERE officer_id = ?
                            )
                        """
                        self.db_ops.execute_query(update_children_query, (photo_url, officer_id))

                        log_debug(f"Updated photo for officer {officer_id}: {search_query}")
                    else:
                        # Mark as processed even if no photo found
                        update_query = """
                            UPDATE Officers
                            SET photo_url = ''
                            WHERE officer_id = ?
                        """
                        self.db_ops.execute_query(update_query, (officer_id,))

                        # Also mark children as processed
                        update_children_query = """
                            UPDATE Officers
                            SET photo_url = ''
                            WHERE master_id = (
                                SELECT master_id FROM Officers WHERE officer_id = ?
                            )
                        """
                        self.db_ops.execute_query(update_children_query, (officer_id,))

                    processed_count += 1

        return processed_count


class PhotoProcessor:
    """Handles officer photo processing using Google Knowledge Graph API with producer-consumer pattern"""

    def __init__(self, db_ops: DatabaseOperations, cache_dir: Optional[str] = None, thread_pool_config: Optional[ThreadPoolConfig] = None):
        self.db_ops = db_ops
        self.cache_dir = cache_dir or os.path.join(global_config.final_dir, "photo_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        self.api_key = os.getenv('GOOGLE_KNOWLEDGE_GRAPH_API_KEY')
        if not self.api_key:
            log_warning("GOOGLE_KNOWLEDGE_GRAPH_API_KEY environment variable not set")

        # Thread pool configuration for concurrent processing
        if thread_pool_config is None:
            self.thread_pool_config = ThreadPoolConfig(
                producer_config=PoolConfig(max_workers=4, queue_size=1000, batch_size=50),
                consumer_config=PoolConfig(max_workers=1, queue_size=1000, batch_size=50)  # Single consumer for API rate limiting
            )
        else:
            self.thread_pool_config = thread_pool_config


    def process_officer_photos(self) -> int:
        """Process all officers and fetch their photos using producer-consumer pattern"""
        log_info("Starting officer photo processing with ThreadPoolManager")

        if not self.api_key:
            log_warning("No Google Knowledge Graph API key available, skipping photo processing")
            return 0

        # Create producer and consumer instances
        producer = PhotoProducer(self.db_ops, self.cache_dir, self.thread_pool_config)
        consumer = PhotoConsumer(self.db_ops, self.thread_pool_config)

        # Collect operations using producer
        operations = producer.collect_operations_parallel(max_workers=4)

        if not operations:
            log_info("No officers found needing photo processing")
            return 0

        log_info(f"Collected {len(operations)} photo search operations")

        # Execute operations using consumer
        processed_count = consumer.execute_operations_parallel(operations)

        # Commit all database changes
        self.db_ops.commit()

        # Calculate updated count (operations that found photos)
        updated_count = sum(1 for op in operations
                          if op.data.get('operation_name') == "search_officer_photo" and
                          op.data.get('photo_found', False))

        log_info(f"Photo processing complete. Processed {processed_count} operations, updated {updated_count} officers with photos.")
        return updated_count