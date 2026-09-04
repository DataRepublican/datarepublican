#!/usr/bin/env python3
"""
database_operations.py - Database operations for IRS 990 data processing

This module contains all database-related operations for the IRS 990 processor,
including CRUD operations for all data models.

This module now uses DuckDB exclusively.

ARCHITECTURE OVERVIEW:
- DatabaseOperations: Main class handling all DuckDB interactions
- GENERIC_INSERT(): Organizes objects by type and inserts in ownership order (Charity→Officer→Grant→Contractor→PoliticalContribution→Address)
- INSERT_BY_TYPE(): For PDC when objects are pre-sorted by type
- bulk_insert(): High-performance batched inserts with client-side UUID generation
- Thread-local connections for multi-threaded safety
- Static ZIP file path cache for performance

KEY CLASSES:
- DatabaseOperations: Main database interface class
- DatabaseOperationType: Enum of operation types (mostly deprecated)
- DatabaseOperation: Represents individual operations (mostly deprecated)

DATABASE CONSTRAINTS:
- DuckDB allows multiple readers but only one writer
- Uses thread-local connections to avoid writer conflicts
- Client-side UUID7 generation for object relationships
- Strict ownership order enforcement for referential integrity

PERFORMANCE FEATURES:
- Preloaded ZIP file path cache at startup
- Batched executemany operations for bulk inserts
- Connection pooling with thread-local storage
- Query timeout protection and error handling
"""

import duckdb
import pandas as pd
import inspect
from typing import Optional, List, Tuple, Dict, Any, Type, Union, Generator, ContextManager
from dataclasses import fields
from datetime import datetime
from pathlib import Path
import uuid
import time
import random
import sys
import os
import threading
from enum import Enum
from functools import lru_cache
from config import global_config
import re
import queue
from contextlib import contextmanager

# Add current directory to path for imports
sys.path.append(os.path.dirname(__file__))

# Import all dataclasses from models package
from models import Address, ZipFile, XMLFile, Charity, Grant, Officer, Contractor, PoliticalContribution, IrsBmf
from models.base import BaseModel
from constants import VALID_STATES, CURRENT_PROCESSING_VERSION, WAL_COMPACTION_TIMEOUT,ENABLE_AUTO_CHECKPOINTS
from logging_utils import log_error, log_debug, log_info, log_warning
from loggingDuckDB import LoggingDuckDBConnection
from constants import ENABLE_CHARITY_DEDUP_CHECK


def _oom_hard_exit(context: str, exc: BaseException) -> None:
    """Force-kill the whole process on DuckDB OOM.

    ``sys.exit`` only raises SystemExit in the *current* thread. Geocoding
    workers call bulk_update from non-main threads, so sys.exit left a zombie
    pipeline stuck in shutdown queue-join while the write connection was
    already invalidated. ``os._exit`` terminates immediately so an outer
    max-files / chunk loop can start a fresh process.
    """
    log_error(f"Out of memory error detected in {context}: {exc}")
    log_error(
        "Hard-exiting process (os._exit) so outer chunk loop can continue "
        "with a clean DuckDB connection"
    )
    try:
        sys.stderr.flush()
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(75)  # EX_TEMPFAIL-ish; non-zero for shell loops


_WRITE_KEYWORD_PATTERN = re.compile(
    r'^(CREATE|DROP|INSERT|UPDATE|DELETE|ALTER|VACUUM|CHECKPOINT)\s',
    re.IGNORECASE
)

# utility function
def is_write_query(query: str) -> bool:
        if not query:
            return False
        # strip() removes leading/trailing whitespace; search from start
        match = _WRITE_KEYWORD_PATTERN.search(query.strip())
        return bool(match)
    
def wal_compaction_timer():
            """Timer function to print and log WAL compaction message"""
            log_info("Compacting Database WAL")
            print("Compacting Database WAL")

class DuckDBPool:
    
                
    def __init__(self, db_path, initial_read=17, max_read=128, auto_checkpoint=False, dbUI=False):
        self.db_path = db_path
        self.log_wrapper_read = global_config.log_sql
        self.log_wrapper_write = global_config.log_sql
        self.wal_timer = threading.Timer(WAL_COMPACTION_TIMEOUT, wal_compaction_timer)
        self.wal_timer.start()
        
        # Build shared config dictionary that EVERY connection will use.
        # DUCKDB_MEMORY_LIMIT lets overnight co-runs (grant_match + snapshot backfill)
        # share a 16GB host without both claiming 8–12GB.
        _mem = os.environ.get("DUCKDB_MEMORY_LIMIT", "6GB")
        self.shared_config = {
            "memory_limit": _mem,
            "threads": str(global_config.db_threads),
            #"access_mode": "READ_ONLY",
            #"enable_progress_bar": "false",
            "enable_object_cache": "true",
            "preserve_insertion_order": "false",
            "checkpoint_threshold": "1TB",
            "wal_autocheckpoint": "1TB",
            # Add any other safe global-ish settings here
        }
        self.write_conn = LoggingDuckDBConnection(db_path, config=self.shared_config) if self.log_wrapper_write else duckdb.connect(db_path, config=self.shared_config)
        self.config_connection(self.write_conn,read_only=False)
        self._lock = threading.Lock()
        self.write_lock = threading.RLock()  # One writer, ehich can be reentrantly grabbed. 
        self.auto_checkpoint = auto_checkpoint
        with self.acquire_write() as conn:
            self._init_schema()
            # Skip CHECKPOINT on init — production DB hits DuckDB UUID/VARCHAR index bug on checkpoint.
            # After unclean shutdown + ART SIGSEGV: stop pipeline, move .wal aside (see repair_geocoding_indexes.py),
            # drop idx_geocoding_status / idx_geocoding_canonical, then restart.
        self.wal_timer.cancel()
        self.wal_timer= None
        self.max_read = max_read
        self.local_pools = threading.local()
        self.created_read = 0
        self.initial_read = initial_read

         # Check for --dbUI flag and start UI if present on a read only connection
        if dbUI or global_config.dbUI:
            try:
                with self.acquire_read() as conn:
                    conn.execute("CALL start_ui();")
                    log_info("Database UI started successfully")
            except Exception as e:
                log_info(f"Failed to start database UI: {e}")
                log_info("Continuing without UI...")
                
    def _new_conn(self, read_only=False):
        """Get a new connection with appropriate configuration"""
        conn = LoggingDuckDBConnection(self.db_path, config=self.shared_config) if (self.log_wrapper_read and read_only) or (self.log_wrapper_write and not read_only) else duckdb.connect(self.db_path, config=self.shared_config)
        self.config_connection(conn,read_only=read_only)
        return conn
      
    @contextmanager
    def acquire_read(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        tid = threading.get_ident()
        if not hasattr(self.local_pools, 'conn'):
            log_debug(f"TID={tid} DEDICATED init RO conn")
            self.local_pools.conn = self._new_conn(read_only=True)
            self.local_pools.health_ok = True
        
        conn = self.local_pools.conn
        if not self.local_pools.health_ok or not self._health_check(conn):
            log_warning(f"TID={tid} Dedicated recreate")
            if hasattr(self.local_pools, 'conn'):
                self.local_pools.conn.close()
            self.local_pools.conn = self._new_conn(read_only=True)
            self.local_pools.health_ok = True
        
        try:
            conn.commit()  # Ensure any pending transactions are resolved before yielding
            yield conn
            self.local_pools.health_ok = True
        except duckdb.ConnectionException as e:
            self.local_pools.conn.close()
            self.local_pools.health_ok = False
            log_warning(f"TID={tid} ConnectionException during read: {e} → reconnecting")
            self.local_pools.conn = self._new_conn(read_only=True)
            self.local_pools.health_ok = True

            raise
        except Exception:
            self.local_pools.health_ok = False
            log_warning(f"TID={tid} Query failed → mark unhealthy")
            raise

    @contextmanager
    def acquire_write(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        with self.write_lock:
            yield self.write_conn
            # Auto-checkpoint on release?
            try:
                try: 
                    self.write_conn.execute("COMMIT")
                except duckdb.TransactionException:
                    pass #don't care if there's no transaction 
                if self.auto_checkpoint:
                    self.write_conn.execute("CHECKPOINT")
            except Exception as e:
                log_warning(f"Auto-checkpoint on release failed: {e}")   
                         
    def config_connection(self, conn,read_only):
        conn.execute("SET enable_progress_bar = false")  # Disable progress bars for better performance
        conn.execute(f"SET threads = {global_config.db_threads}")
        conn.execute("SET enable_object_cache = true")
        if not read_only:
            conn.execute("SET wal_autocheckpoint='1TB'")
            conn.execute("SET checkpoint_threshold='1TB'")
        #conn.execute("SET max_temp_directory_size = '100GB'")  # Increase temp directory size - DEFAULT is ALL

        #try:
        #    conn.execute("PRAGMA temp_directory = '/tmp'")  # Store temporary data in memory
        #except Exception:
        #    pass  # Ignore if not supported
        #try:
        #    conn.execute("SET checkpoint_threshold = '500MB'")  # WAL size doesn't matter in grok benchmark.
        #    conn.execute("PRAGMA checkpoint_threshold='500MB'")   # or '500MB'
        #    conn.execute("PRAGMA wal_autocheckpoint='500MB'")    # same thing, older name

        #except Exception as e:
        #    log_warning(f"exception setting checkpoint_threshold {e}")
        #    pass  # Ignore if not supported
        #conn.execute("SET preserve_insertion_order = false")  # Allow reordering for better performance
        #conn.execute("PRAGMA force_checkpoint;") unneccessary
        #conn.execute("SET enable_logging = true")
        #conn.execute("SET logging_level = 'DEBUG'")
        
        # THIS IS DEAD CODE, because duckdb doesn't support mixing modes. You can only set it at startup
        # and it doesn't allow a mix of modes. 
        #if read_only:
        #    conn.execute("SET access_mode = READ_ONLY")
        #else:
        #    conn.execute("SET access_mode = READ_WRITE")

    def _health_check(self, conn):
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except Exception as e:
            log_warning(f"Health check fail: {e}")
            return False

    def _new_conn(self, read_only):
        wrapper = self.log_wrapper_read if read_only else self.log_wrapper_write
        conn = LoggingDuckDBConnection(self.db_path, config=self.shared_config) if wrapper else duckdb.connect(self.db_path, config=self.shared_config)
        self.config_connection(conn, read_only=read_only)
        return conn
        
    def close(self):
        # Close local thread conns if any active
        for attr in dir(self.local_pools.__class__):
            if attr.startswith('conn'):  # Cleanup if needed
                attr_conn = getattr(self.local_pools, attr)
                if attr_conn:
                    attr_conn.close()
        if hasattr(self, 'write_conn'):
            self.write_conn.close()
            
    def _init_schema(self):
            """Initialize database schema if not already present"""
            # Check if schema is already initialized
            try:
                result = self.write_conn.execute("SELECT table_name FROM duckdb_tables() WHERE table_name='Charities'").fetchone()
                if result:
                    return  # Schema already exists
            except duckdb.CatalogException:
                pass  # Table doesn't exist, continue with schema creation

            # Read and execute schema_duckdb.sql
            schema_path = os.path.join(os.path.dirname(__file__), 'schema_duckdb.sql')
            try:
                with open(schema_path, 'r') as f:
                    schema_sql = f.read()
                self.write_conn.execute(schema_sql)
                self.write_conn.commit()
            except Exception as e:
                log_error(f"Failed to initialize DuckDB database schema: {e}")
                raise
        



class DatabaseOperationType(Enum):
    """
    Enumeration of database operation types for flexible processing.

    MOSTLY DEPRECATED: These operation types were used in the old operation-based
    processing model. The new PDC (PendingDatabaseContext) approach handles
    operations internally without explicit operation types.

    Still used for:
    - XML_FILE_UPDATE: Updating XML file processing status
    - OPTIMIZE_DATABASE: Database optimization operations
    - PROGRESS_UPDATE: Progress bar updates
    """
    XML_FILE_UPDATE = "xml_file_update"
    UPDATE_XML_EIN = "update_xml_ein"
    OPTIMIZE_DATABASE = "optimize_database"
    GENERIC_UPDATE = "generic_update"
    GENERIC_INSERT = "generic_insert"
    INSERT_BY_TYPE = "insert_by_type"
    INSERT_CHARITY = "insert_charity"
    INSERT_ADDRESS = "insert_address"
    PROGRESS_UPDATE = "progress_update"
    INSERT_GEOCODING = "insert_geocoding"
    UPDATE_GEOCODING = "update_geocoding"
    UPDATE_ADDRESS_GEOCODING = "update_address_geocoding"
    AUTHORITATIVE_EIN_UPDATE = "AUTHORITATIVE_EIN_UPDATE"


class DatabaseOperation:
    """
    Represents a single database operation with its data and dependencies.

    DEPRECATED: This class was used in the old operation-based processing model.
    The new PDC (PendingDatabaseContext) approach handles operations internally
    without explicit DatabaseOperation objects.

    Still used for XML file updates and progress tracking operations.
    """

    def __init__(self, operation_type: DatabaseOperationType, data: Any, xml_id: Optional[str] = None,
                  dependencies: Optional[List[str]] = None):
        self.operation_type = operation_type
        self.data = data
        self.xml_id = xml_id
        self.dependencies = dependencies or []  # List of operation types this depends on


class DatabaseOperations:
    """
    Handles all DuckDB operations for IRS 990 data processing.

    This is the main database interface class that provides:
    - Connection management with thread-local connections
    - Generic CRUD operations for all dataclass types
    - Bulk insert operations with ownership order enforcement
    - ZIP file path caching for performance
    - Schema initialization and optimization

    THREADING MODEL:
    - Uses thread-local connections to avoid DuckDB's single-writer constraint
    - Multiple readers allowed, but only one writer per connection
    - Static ZIP cache shared across all instances

    PERFORMANCE FEATURES:
    - Preloaded ZIP file path cache at startup
    - Batched executemany operations for bulk inserts
    - Client-side UUID7 generation for object relationships
    - Connection pooling and reuse

    KEY METHODS:
    - GENERIC_INSERT(): Organizes mixed objects by type and inserts in ownership order
    - INSERT_BY_TYPE(): For PDC when objects are pre-sorted by type
    - bulk_insert(): High-performance batched inserts
    - select_dataclass(): Generic SELECT with reflection-based field mapping
    """

    # SQL logging is now read directly from global_config

    # Static cache for zip_id -> file_path mapping - preloaded at startup
    _zip_path_cache: Dict[str, str] = {}
    _zip_file_cache: Dict[str, ZipFile] = {}  # Cache for ZipFile objects
    _zip_cache_lock = threading.RLock()  # Reentrant lock for thread safety

    # Global table metadata cache (no lock needed - loaded at startup, never modified)
    _table_metadata_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def generate_uuid_v7() -> str:
        """Generate a UUID v7 (time-ordered) - now delegates to uuid7 module"""
        from uuid7 import generate_uuid_v7
        return generate_uuid_v7()

    def __init__(self, db_path: str, read_only: bool = False, memory_limit: str = "6GB", threads: Optional[int] = None, dbUI: bool = False, query_timeout: int = 300, init_schema: bool = True):
        """
        Initialize DuckDB connection with performance optimizations.

        Sets up thread-local connections, preloads ZIP cache, and optionally initializes schema.
        Configures DuckDB with performance settings for bulk operations.

        Args:
            db_path: Path to DuckDB database file
            read_only: Whether to open database in read-only mode
            memory_limit: Memory limit for DuckDB (default: 4GB)
            threads: Number of threads for DuckDB (default: auto)
            dbUI: Whether to start DuckDB's web UI
            query_timeout: Query timeout in seconds (default: 300)
            init_schema: Whether to initialize schema if not present (default: True)

        THREADING: Creates thread-local connections to avoid DuckDB's single-writer constraint.
        PERFORMANCE: Preloads ZIP file cache and applies bulk operation optimizations.
        """
        self.db_path = db_path
        # SQL logging is now read directly from global_config
        self.read_only = read_only
        self.memory_limit = memory_limit
        self.threads = threads
        self.dbUI = dbUI
        self.query_timeout = query_timeout
        self.init_schema = init_schema
        self.main_thread_id = threading.get_ident()
        self._init_connection()
        self._preload_zip_file_cache()
        self._preload_table_metadata_cache()
        
    _pool: Optional[DuckDBPool] = None

    @classmethod
    def initialize_pool(cls, db_path, **pool_kwargs):
        if cls._pool is None:
            cls._pool = DuckDBPool(db_path, **pool_kwargs)
        return cls._pool

    @classmethod
    def get_pool(cls) -> DuckDBPool:
        if cls._pool is None:
            raise RuntimeError("Pool not initialized")
        return cls._pool
    
        
    
    @contextmanager
    def acquire_read_conn(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        with self._pool.acquire_read() as conn:
            yield conn
    
    @contextmanager
    def acquire_write_conn(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        with self._pool.acquire_write() as conn:
            yield conn

    def commit(self) -> None:
        """Commit pending writes on the shared writer connection.

        Many call sites (update_zip_status, ratio updates, etc.) invoke self.commit().
        DuckDBPool.acquire_write already issues COMMIT on release; this method makes
        that contract explicit and safe when no transaction is open.
        """
        if self._pool is None:
            return
        with self.acquire_write_conn() as conn:
            try:
                conn.commit()
            except duckdb.TransactionException:
                pass
            except Exception:
                try:
                    conn.execute("COMMIT")
                except Exception:
                    pass

    @classmethod
    def bootstrap(cls, db_path: str, **pool_kwargs) -> DuckDBPool:
        cls.initialize_pool(db_path, **pool_kwargs)
        return cls._pool
        
    @staticmethod
    def closePool():
        if DatabaseOperations._pool is None:
            log_info("Pool not initialized")
            return
        DatabaseOperations._pool.close()
        DatabaseOperations._pool = None
        
    def close(self):
        """Explicitly close the database connection pool"""
        DatabaseOperations.closePool()

    def __del__(self):
        """Cleanup database connection on object destruction"""
        self.close()

    def _init_connection(self):
        """Initialize DuckDB connection and schema"""
        # Set up timer for WAL compaction
        import threading
        import time

    

       

    def _preload_zip_file_cache(self):
        """Preload all zip_id -> file_path mappings and ZipFile objects into the static cache at startup"""
        import time
        with DatabaseOperations._zip_cache_lock:
            if DatabaseOperations._zip_path_cache:
                # Already preloaded
                return

            # Skip cache preload if schema initialization was skipped (tables may not exist)
            if not self.init_schema:
                log_debug("Skipping zip path cache preload (schema initialization disabled)")
                return

            try:
                log_info("Preloading zip path and object cache...")
                start_time = time.time()
                # Query all ZipFile records from database
                zip_files = self.select_dataclass(ZipFile, order_by="zip_id")
                query_time = time.time() - start_time
                log_info(f"Loaded {len(zip_files)} ZipFile objects from database in {query_time:.3f}s")

                # Populate the cache with zip_id -> file_path mappings and ZipFile objects
                cache_start = time.time()
                for zip_file in zip_files:
                    DatabaseOperations._zip_path_cache[zip_file.zip_id] = zip_file.file_path
                    DatabaseOperations._zip_file_cache[zip_file.zip_id] = zip_file
                cache_time = time.time() - cache_start

                log_info(f"Zip path cache preloaded with {len(DatabaseOperations._zip_path_cache)} entries in {cache_time:.3f}s")
                log_info(f"Zip object cache preloaded with {len(DatabaseOperations._zip_file_cache)} entries")

            except Exception as e:
                log_error(f"Failed to preload zip path cache: {e}")
                # Continue without cache - operations will fall back to database queries

    def _preload_table_metadata_cache(self):
        """Preload table metadata cache from pickled file or build it"""
        import pickle
        import os
        import time

        cache_file = os.path.join(os.path.dirname(__file__), 'table_metadata_cache.pkl')

        if DatabaseOperations._table_metadata_cache:
            # Already preloaded
            return

        try:
            # Try to load from pickled file first
            if os.path.exists(cache_file):
                with open(cache_file, 'rb') as f:
                    DatabaseOperations._table_metadata_cache = pickle.load(f)
                log_info(f"Loaded table metadata cache from {cache_file} with {len(DatabaseOperations._table_metadata_cache)} entries")
                return

            # Build cache from database schema with timing
            log_info("Building table metadata cache...")
            tables = ['ZipFiles', 'XmlFiles', 'Charities', 'Officers', 'Grants', 'Contractors', 'PoliticalContributions', 'Addresses', 'Geocoding', 'IrsBmf']

            total_start = time.time()
            for table in tables:
                try:
                    table_start = time.time()
                    columns = self._get_table_columns(table)
                    table_time = time.time() - table_start
                    DatabaseOperations._table_metadata_cache[table] = {
                        'columns': columns,
                        'column_count': len(columns)
                    }
                    log_info(f"  {table}: {len(columns)} columns in {table_time:.3f}s")
                except Exception as e:
                    log_warning(f"Could not get metadata for table {table}: {e}")

            total_time = time.time() - total_start
            log_info(f"Table metadata cache built with {len(DatabaseOperations._table_metadata_cache)} entries in {total_time:.3f}s")

            # Save to pickled file for future use
            try:
                with open(cache_file, 'wb') as f:
                    pickle.dump(DatabaseOperations._table_metadata_cache, f)
                log_info(f"Saved table metadata cache to {cache_file}")
            except Exception as e:
                log_warning(f"Could not save table metadata cache: {e}")

        except Exception as e:
            log_error(f"Failed to preload table metadata cache: {e}")
            # Continue without cache

    

    def execute_query(self, query: str, params: Optional[Tuple] = None, conn: Optional[duckdb.DuckDBPyConnection] = None) -> Any:
        """
        Execute a query with timeout protection and enhanced error handling.

        Uses thread-local connections for thread safety. Handles DuckDB-specific errors
        and provides detailed logging when SQL logging is enabled.

        Args:
            query: SQL query string
            params: Query parameters tuple
            conn: Optional connection override (uses thread-local by default)

        Returns:
            DuckDB result object

        Raises:
            RuntimeError: For query execution failures with detailed error messages
        """

        # Don't log here if we're using LoggingDuckDBConnection - it will handle logging
        if global_config.log_sql and not isinstance(conn, LoggingDuckDBConnection):
            import inspect
            # Get the caller's frame, skipping internal functions
            frame = inspect.currentframe()
            if frame:
                frame = frame.f_back
                while frame and (frame.f_code.co_filename.endswith(('database_operations.py', 'logging_utils.py')) or
                                'execute_query' in frame.f_code.co_name):
                    frame = frame.f_back

                if frame:
                    filename = frame.f_code.co_filename
                    line_number = frame.f_lineno
                    function_name = frame.f_code.co_name
                    log_info(f"SQL from {filename}:{line_number} in {function_name}: {query}")
                    if params:
                        log_info(f"Parameters: {params}")

        try:
            if is_write_query(query):
                if conn is None:
                    with self.acquire_write_conn() as inner_conn:
                        return inner_conn.execute(query, params or ())
                else:
                    return conn.execute(query, params or ())
            else:
                if conn is None:
                    with self.acquire_read_conn() as inner_conn:
                        return inner_conn.execute(query, params or ())
                else:
                    return conn.execute(query, params or ())
        except (duckdb.CatalogException, duckdb.BinderException, duckdb.SyntaxException,
                duckdb.ConstraintException, duckdb.DataError) as e:
            # Handle query-specific errors (syntax, constraint violations, table not found, etc.)
            error_str = str(e).lower()
            if "out of memory" in error_str or "failed to offload data block" in error_str or "failed to pin" in error_str:
                _oom_hard_exit("execute_query", e)
            error_msg = f"Query execution failed: {str(e)}"
            if "timeout" in str(e).lower() or "interrupt" in str(e).lower():
                error_msg = f"Query timed out or was interrupted: {str(e)}"
            log_error(error_msg)
            raise RuntimeError(error_msg) from e
        except duckdb.ConnectionException as e:
            # Handle connection-related errors
            error_str = str(e).lower()
            if "out of memory" in error_str or "failed to offload data block" in error_str or "failed to pin" in error_str:
                _oom_hard_exit("execute_query/connection", e)
            error_msg = f"Database connection error: {str(e)}"
            log_error(error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            # Check for out-of-memory errors specifically
            error_str = str(e).lower()
            if "out of memory" in error_str or "failed to offload data block" in error_str or "failed to pin" in error_str:
                _oom_hard_exit("execute_query/other", e)
            # Handle any other unexpected errors
            error_msg = f"Unexpected database error: {str(e)}"
            log_error(error_msg)
            raise RuntimeError(error_msg) from e

    def select_dataclass(self, dataclass_type: Type, where_clause: str = "", params: Optional[Tuple] = None,
                        order_by: str = "", limit: Optional[int] = None, offset: Optional[int] = None,
                        df_threshold: int = 10000) -> List[Any]:
        """
        Generic method to select records and convert them to dataclass instances using reflection.

        Uses Python dataclass introspection to dynamically build SELECT queries and map
        database columns to dataclass fields. Handles field filtering for database compatibility.

        Args:
            dataclass_type: The dataclass type to instantiate (e.g., Charity, Address)
            where_clause: Optional WHERE clause (without the WHERE keyword)
            params: Parameters for the WHERE clause
            order_by: Optional ORDER BY clause (without the ORDER BY keyword)
            limit: Optional LIMIT clause
            offset: Optional OFFSET clause
            df_threshold: Threshold for using DataFrame vs fetchall (default: 10000)

        Returns:
            List of dataclass instances with proper field mapping and type conversion

        REFLECTION: Uses dataclass.fields() to dynamically determine table schema
        PERFORMANCE: Filters out non-init fields and missing database columns
        """
        # Get table name from dataclass name (pluralize by adding 's' or 'ies')
        table_name = self._get_table_name(dataclass_type)

        # Get field names from dataclass, but filter out fields that don't exist in the table
        all_field_names = [f.name for f in fields(dataclass_type)]
        field_names = self._filter_existing_columns(table_name, all_field_names)

        # Build SELECT query
        select_fields = ", ".join(field_names)
        query = f"SELECT {select_fields} FROM {table_name}"

        if where_clause:
            query += f" WHERE {where_clause}"

        if order_by:
            query += f" ORDER BY {order_by}"

        if limit:
            query += f" LIMIT {limit}"

        if offset:
            query += f" OFFSET {offset}"

        # Determine if we should use DataFrame for large result sets
        use_dataframe = False
 
        # Execute main query
        result = self.execute_query(query, params)

        # Use fetchall for smaller result sets
        rows = result.fetchall()
        row_dicts = [dict(zip(field_names, row)) for row in rows]

        # Convert row dicts to dataclass instances
        instances = []
        init_fields = {f.name for f in fields(dataclass_type) if f.init}
        for row_dict in row_dicts:
            # Filter out fields that have init=False since they can't be passed to __init__
            filtered_dict = {k: v for k, v in row_dict.items() if k in init_fields}
            # Instantiate dataclass with only the init fields
            instance = dataclass_type(**filtered_dict)
            # Set non-init fields manually
            for k, v in row_dict.items():
                if k not in init_fields:
                    setattr(instance, k, v)
            instances.append(instance)

        return instances

    def _get_table_columns(self, table_name: str, conn=None) -> List[str]:
        """Get column names for a table, cached for performance"""
        # Check global metadata cache first
        if table_name in DatabaseOperations._table_metadata_cache:
            return DatabaseOperations._table_metadata_cache[table_name]['columns']

        # Fallback to database query - use thread-local connection for thread safety
        with self.acquire_read_conn() as conn:
            try:
                result = conn.execute(f"DESCRIBE {table_name}")
                columns = [row[0] for row in result.fetchall()]

                # Cache the result (thread-safe since dict operations are atomic for simple cases)
                DatabaseOperations._table_metadata_cache[table_name] = {
                    'columns': columns,
                    'column_count': len(columns)
                }

                return columns
            except Exception:
                return []

    def _filter_existing_columns(self, table_name: str, field_names: List[str]) -> List[str]:
        """Filter field names to only include columns that exist in the table"""
        table_columns = self._get_table_columns(table_name)
        if not table_columns:
            # If DESCRIBE fails, return all fields (fallback)
            return field_names

        # Filter field names to only include existing columns
        return [field for field in field_names if field in table_columns]

    def _get_table_name(self, dataclass_type: Type) -> str:
        """Get table name from dataclass type, cached for performance"""
        class_name = dataclass_type.__name__
        # Special cases based on actual table names in schema
        table_name_map = {
            'XMLFile': 'XmlFiles',
            'ZipFile': 'ZipFiles',
            'IrsBmf': 'IrsBmf',
            'PoliticalContribution': 'PoliticalContributions',
            'Geocoding': 'Geocoding',
            'FecCommittee': 'fec_committees',
            'FecIndividualContribution': 'fec_individual_contributions',
            'FecCommitteeTransaction': 'fec_committee_transactions',
            'FecCandidateSpending': 'fec_candidate_spendings',
            'FecOperatingExpenditure': 'fec_operating_expenditures',
            'MedicareProvider': 'medicare_providers',
            'SanctionedEntity': 'sanctioned_entities',
            'SanctionedName': 'sanctioned_names',
            'SanctionedIdentifier': 'sanctioned_identifiers',
            'SanctionedProgram': 'sanctioned_programs',
            'DotCarrier': 'dot_carriers',
        }

        if class_name in table_name_map:
            return table_name_map[class_name]

        # Simple pluralization rules
        if class_name.endswith('y'):
            return class_name[:-1] + 'ies'
        elif class_name.endswith('s') or class_name.endswith('sh') or class_name.endswith('ch') or class_name.endswith('x') or class_name.endswith('z'):
            return class_name + 'es'
        else:
            return class_name + 's'


    # ZipFile operations
    def insert_zip_file(self, zip_file: ZipFile) -> str:
        """Insert ZipFile into database using generic insert_dataclass method"""
        ids = self.bulk_insert([zip_file])
        zip_id = ids[0] if ids else ""
        # Update cache if insertion successful
        if zip_id:
            with DatabaseOperations._zip_cache_lock:
                DatabaseOperations._zip_path_cache[zip_id] = zip_file.file_path
                DatabaseOperations._zip_file_cache[zip_id] = zip_file
        return zip_id

    def update_zip_status(self, zip_id: str, status: str):
        """Update ZIP file processing status"""
        self.execute_query("""
            UPDATE ZipFiles SET status = ?, processed_date = ?
            WHERE zip_id = ?
        """, (status, datetime.now().isoformat(), zip_id))
        # No need to update path cache for status changes
        self.commit()

    def get_zip_file(self, zip_id: str) -> Optional[ZipFile]:
        """Get ZipFile from cache or database"""
        with DatabaseOperations._zip_cache_lock:
            # Try direct lookup first
            if zip_id in DatabaseOperations._zip_file_cache:
                return DatabaseOperations._zip_file_cache[zip_id]

        # Fallback to database query if not in cache
        zip_files = self.select_dataclass(ZipFile, where_clause="zip_id = ?", params=(zip_id,))
        if zip_files:
            zip_file = zip_files[0]
            # Cache the result for future use
            with DatabaseOperations._zip_cache_lock:
                DatabaseOperations._zip_file_cache[zip_id] = zip_file
            return zip_file
        return None

    def get_zip_file_path(self, zip_id: str) -> Optional[str]:
        """Get ZIP file path from cache"""
        with DatabaseOperations._zip_cache_lock:
            # Try direct lookup first
            if zip_id in DatabaseOperations._zip_path_cache:
                return DatabaseOperations._zip_path_cache[zip_id]

        # Fallback to database query if not in cache
        zip_files = self.select_dataclass(ZipFile, where_clause="zip_id = ?", params=(zip_id,))
        if zip_files:
            zip_file = zip_files[0]
            # Cache the result for future use
            with DatabaseOperations._zip_cache_lock:
                DatabaseOperations._zip_path_cache[zip_file.zip_id] = zip_file.file_path
            return zip_file.file_path
        return None

    # XMLFile operations
    def insert_xml_file(self, xml_file: XMLFile) -> str:
        """Insert XMLFile into database using generic insert_dataclass method"""
        ids = self.bulk_insert([xml_file])
        return ids[0] if ids else ""

    def get_unprocessed_xml_files(self, processing_version: int, max_files: Optional[int] = None) -> List[XMLFile]:
        """Get unprocessed XML files"""
        where_clause = "processed = FALSE OR processing_version < ?"
        params = (processing_version,)
        order_by = "zip_id, filename"
        limit = max_files

        return self.select_dataclass(XMLFile, where_clause=where_clause, params=params, order_by=order_by, limit=limit)

    def mark_xml_processed(self, xml_id: str, processing_version: int):
        """Mark XML file as processed"""
        self.execute_query("""
            UPDATE XmlFiles SET processed = TRUE, processing_version = ?, error_message = ?, processed_at = ?
            WHERE xml_id = ?
        """, (processing_version, "success", datetime.now().isoformat(), xml_id))
        self.commit()

    def mark_xml_error(self, xml_id: str, processing_version: int, error_msg: str):
        """Mark XML file as having an error"""
        self.execute_query("""
            UPDATE XmlFiles SET processed = TRUE, processing_version = ?, error_message = ?, processed_at = ?
            WHERE xml_id = ?
        """, (processing_version, error_msg, datetime.now().isoformat(), xml_id))
        self.commit()

    def update_xml_ein(self, xml_id: str, ein: str):
        """Update XML file with EIN after parsing"""
        self.execute_query("UPDATE XmlFiles SET ein = ? WHERE xml_id = ?", (ein, xml_id))
        self.commit()

    def execute_update_xml_ein_operation(self, operation: DatabaseOperation, conn=None):
        """Execute UPDATE_XML_EIN operation"""
        with self.acquire_write_conn() as conn:
            xml_id = operation.xml_id
            data = operation.data
            ein = data.get("ein") if data else None
            if ein:
                conn.execute("UPDATE XmlFiles SET ein = ? WHERE xml_id = ?", (ein, xml_id))

    def get_addresses_for_geocoding(self, limit: Optional[int] = None, last_address_id: Optional[str] = None) -> List[Address]:
        """Get addresses that need geocoding, with max primary key pagination support"""
        where_clause = "geocoding_id IS NULL AND (po_box IS NULL OR po_box = '') AND colocator IS NULL AND master_id IS NULL AND canonical_address IS NOT NULL AND canonical_address != ''"
        if last_address_id is not None:
            where_clause += " AND address_id > ?"
            params = (last_address_id,)
        else:
            params = None
        return self.select_dataclass(Address, where_clause=where_clause, params=params, order_by="address_id", limit=limit)


    def update_address_geocoding_by_canonical(self, canonical_address: str, geocoding_id: Optional[str] = None, colocator: Optional[str] = None):
        """Update all addresses with a specific canonical_address with geocoding information and propagate colocator to owners"""
        if not canonical_address:
            return

        # Update addresses using canonical_address
        if geocoding_id is not None and colocator is not None:
            self.execute_query("""
                UPDATE Addresses SET geocoding_id = ?, colocator = ?
                WHERE canonical_address = ?
            """, (geocoding_id, colocator, canonical_address))
        elif geocoding_id is not None:
            self.execute_query("""
                UPDATE Addresses SET geocoding_id = ?
                WHERE canonical_address = ?
            """, (geocoding_id, canonical_address))
        elif colocator is not None:
            self.execute_query("""
                UPDATE Addresses SET colocator = ?
                WHERE canonical_address = ?
            """, (colocator, canonical_address))

        # If colocator was set, also update the owner objects for all addresses with this canonical_address
        if colocator is not None:
            # Get address details for all addresses with this canonical_address
            address_info_list = self.execute_query("""
                SELECT address_type, owner_id FROM Addresses WHERE canonical_address = ?
            """, (canonical_address,)).fetchall()

            for address_info in address_info_list:
                if address_info and len(address_info) >= 2:
                    address_type, owner_id = address_info[0], address_info[1]
                    if owner_id:  # Only update if we have an owner_id
                        if address_type == 'charity':
                            self.execute_query("""
                                UPDATE Charities SET colocator = ? WHERE charity_id = ?
                            """, (colocator, owner_id))
                        elif address_type == 'grant':
                            self.execute_query("""
                                UPDATE Grants SET colocator = ? WHERE grant_id = ?
                            """, (colocator, owner_id))
                        elif address_type == 'contractor':
                            self.execute_query("""
                                UPDATE Contractors SET colocator = ? WHERE contractor_id = ?
                            """, (colocator, owner_id))
                        elif address_type == 'politicalcontribution':
                            self.execute_query("""
                                UPDATE PoliticalContributions SET colocator = ? WHERE political_id = ?
                            """, (colocator, owner_id))

        self.commit()

    def update_address_po_box_and_colocator(self, address_id: str, po_box: str, colocator: str):
        """Update address with PO Box and colocator information and propagate colocator to owner"""
        self.execute_query("""
            UPDATE Addresses SET po_box = ?, colocator = ?
            WHERE address_id = ?
        """, (po_box, colocator, address_id))

        # Also update the owner object with colocator
        address_info = self.execute_query("""
            SELECT address_type, owner_id FROM Addresses WHERE address_id = ?
        """, (address_id,)).fetchone()

        if address_info and len(address_info) >= 2:
            address_type, owner_id = address_info[0], address_info[1]
            if owner_id:  # Only update if we have an owner_id
                if address_type == 'charity':
                    self.execute_query("""
                        UPDATE Charities SET colocator = ? WHERE charity_id = ?
                    """, (colocator, owner_id))
                elif address_type == 'grant':
                    self.execute_query("""
                        UPDATE Grants SET colocator = ? WHERE grant_id = ?
                    """, (colocator, owner_id))
                elif address_type == 'contractor':
                    self.execute_query("""
                        UPDATE Contractors SET colocator = ? WHERE contractor_id = ?
                    """, (colocator, owner_id))
                elif address_type == 'politicalcontribution':
                    self.execute_query("""
                        UPDATE PoliticalContributions SET colocator = ? WHERE political_id = ?
                    """, (colocator, owner_id))

        self.commit()

    def update_charity_percentiles(self, ein: str, tax_year: int, comp_ptile: Optional[float] = None,
                                    travel_ptile: Optional[float] = None, conferences_ptile: Optional[float] = None,
                                    grants_ptile: Optional[float] = None, foreign_ptile: Optional[float] = None):
        """Update charity percentile rankings"""
        self.execute_query("""
            UPDATE Charities SET
                comp_ptile = ?,
                travel_ptile = ?,
                conferences_ptile = ?,
                grants_ptile = ?,
                foreign_expenses_ptile = ?
            WHERE ein = ? AND tax_year = ?
        """, (comp_ptile, travel_ptile, conferences_ptile, grants_ptile, foreign_ptile, ein, tax_year))
        self.commit()

    def get_charities_for_percentiles(self) -> List[Tuple]:
        """Get charities for percentile calculation"""
        result = self.execute_query("""
            SELECT org_type, tax_year, ein, comp_pct, travel_pct, conferences_pct, grants_pct, foreign_expenses_pct
            FROM Charities
            WHERE denominator > 0
            ORDER BY org_type, tax_year
        """)
        return result.fetchall()

    def get_latest_charities_for_export(self) -> List[Charity]:
        """Get latest charities for export (most recent tax year for each EIN)"""
        return self.select_dataclass(Charity, where_clause="""
            tax_year = (
                SELECT MAX(tax_year)
                FROM Charities c2
                WHERE c2.ein = Charities.ein
            )
        """)

    def get_latest_charities_for_export_batch(self, offset: int, limit: int) -> List[Tuple]:
        """Get batch of latest charities for export (most recent tax year for each EIN)"""
        query = """
            SELECT tax_year, filer_ein, filer_name, receipt_amt, govt_amt, contrib_amt,
                   org_type, total_exp, prog_exp, travel_amt, conferences_amt,
                   officer_comp, comp_pct, comp_ptile, travel_pct, travel_ptile,
                   conferences_pct, conferences_ptile, grants_pct, grants_ptile,
                   foreign_expenses_pct, foreign_expenses_ptile, grift_ratio,
                   total_assets, form_type, denominator, foreign_office, foreign_expenses,
                   grants_to_others, domestic_misrep_flag, xml_name
            FROM Charities
            WHERE tax_year = (
                SELECT MAX(tax_year)
                FROM Charities c2
                WHERE c2.ein = Charities.ein
            )
            ORDER BY filer_ein
            LIMIT ? OFFSET ?
        """
        result = self.execute_query(query, (limit, offset))
        return result.fetchall() if result else []

    def get_grants_for_export(self) -> List[Grant]:
        """Get all grants for export"""
        return self.select_dataclass(Grant)

    def get_grants_for_export_batch(self, offset: int, limit: int) -> List[Tuple]:
        """Get batch of grants for export"""
        query = """
            SELECT filer_ein, filer_name, recipient_ein, grant_amt, tax_year,
                   filer_colocator, grantee_colocator
            FROM Grants
            ORDER BY filer_ein, recipient_ein
            LIMIT ? OFFSET ?
        """
        result = self.execute_query(query, (limit, offset))
        return result.fetchall() if result else []

    def get_contractors_for_export(self) -> List[Contractor]:
        """Get all contractors for export"""
        return self.select_dataclass(Contractor)

    def get_contractors_for_export_batch(self, offset: int, limit: int) -> List[Tuple]:
        """Get batch of contractors for export"""
        query = """
            SELECT filer_ein, name, amount, ein, address, zip_code,
                   po_box, tax_year, colocator
            FROM Contractors
            ORDER BY filer_ein, name
            LIMIT ? OFFSET ?
        """
        result = self.execute_query(query, (limit, offset))
        return result.fetchall() if result else []

    def get_political_contributions_for_export(self) -> List[PoliticalContribution]:
        """Get all political contributions for export"""
        return self.select_dataclass(PoliticalContribution)

    def get_political_contributions_for_export_batch(self, offset: int, limit: int) -> List[Tuple]:
        """Get batch of political contributions for export"""
        query = """
            SELECT filer_ein, recipient, amount, recipient_address,
                   recipient_zip, recipient_po_box, tax_year, colocator
            FROM PoliticalContributions
            ORDER BY filer_ein, recipient
            LIMIT ? OFFSET ?
        """
        result = self.execute_query(query, (limit, offset))
        return result.fetchall() if result else []

    def create_latest_charities_table(self):
        """Create LatestCharities table with most recent filings"""
        self.execute_query("""
            CREATE OR REPLACE TABLE LatestCharities AS
            SELECT c.*
            FROM Charities c
            INNER JOIN (
                SELECT ein, MAX(tax_year) as max_year
                FROM Charities
                GROUP BY ein
            ) latest ON c.ein = latest.ein AND c.tax_year = latest.max_year
        """)
        self.commit()

    def update_grant_ein(self, grant_id: str, recipient_ein: str):
        """Update grant with matched EIN"""
        self.execute_query("""
            UPDATE Grants SET recipient_ein = ? WHERE grant_id = ?
        """, (recipient_ein, grant_id))
        self.commit()

    def get_grants_without_ein(self) -> List[Grant]:
        """Get grants with unknown EINs for matching"""
        return self.select_dataclass(Grant, where_clause="recipient_ein IS NULL OR recipient_ein = ''")
    
    def get_last_bmf_ein(self) -> Optional[str]:
        """Get the highest EIN already processed in IrsBmf table for resume."""
        result = self.execute_query('SELECT MAX(ein) FROM "IrsBmf"').fetchone()
        return result[0] if result and result[0] else None

    def GENERIC_INSERT(self, objects: List[BaseModel]) -> List[str]:
        """
        Generic insert method that organizes objects by class type and inserts them
        in ownership order from the Architecture.md file.

        This is the PRIMARY insert method for mixed object collections. It enforces
        the strict ownership hierarchy to maintain referential integrity:
        Charity →  IrsBmf → Officer → Grant → Contractor → PoliticalContribution → Address

        Args:
            objects: List of BaseModel instances to insert (mixed types allowed)

        Returns:
            List of generated IDs in the order they were inserted

        OWNERSHIP ORDER: Ensures parent objects are inserted before their children
        THREADING: Safe for multi-threaded use with thread-local connections
        PERFORMANCE: Organizes by type first, then bulk inserts each type
        """
        for obj in objects:
            if not isinstance(obj, BaseModel):
                raise ValueError("All objects must be BaseModel instances")

        # Organize objects by type
        objects_by_type = {}
        for obj in objects:
            obj_type = type(obj).__name__
            if obj_type not in objects_by_type:
                objects_by_type[obj_type] = []
            objects_by_type[obj_type].append(obj)

        # Insert in ownership order: Charity first, then related objects, Address last
        # Order: Charity, Officer, Grant, Contractor, PoliticalContribution, Address
        ownership_order = ['IrsBmf','Charity', 'Officer', 'Grant', 'Contractor', 'PoliticalContribution', 'Address']
        all_ids = []

        for obj_type in ownership_order:
            if obj_type in objects_by_type:
                ids = self.bulk_insert(objects_by_type[obj_type])
                all_ids.extend(ids)

        return all_ids

    def INSERT_BY_TYPE(self, objects: List[BaseModel], obj_type: str, commit_batches: bool = True, conn: Optional[duckdb.DuckDBPyConnection] = None) -> List[str]:
        """
        Insert method for DatabasePendingContext that takes a list of objects of the same type
        and calls bulk_insert directly (no sorting needed since DPC has already sorted by type).

        This is the SECONDARY insert method used by PDC when objects are already grouped
        by type. PDC handles ownership ordering, so this method just validates and bulk inserts.

        Args:
            objects: List of BaseModel instances of the same type to insert
            obj_type: The type name (for validation/logging)

        Returns:
            List of generated IDs

        VALIDATION: Ensures all objects are of the specified type
        PDC INTEGRATION: Called by PendingDatabaseContext.save_to_database()
        PERFORMANCE: Direct bulk insert without type sorting overhead
        """
        for obj in objects:
            if not isinstance(obj, BaseModel):
                raise ValueError(f"All objects must be BaseModel instances {obj}")
            if type(obj).__name__.lower() != obj_type.lower():
                raise ValueError(f"All objects must be of type {obj_type}, got {type(obj).__name__}")

        return self.bulk_insert(objects, commit_batches=commit_batches, conn=conn)

    # Geocoding operations
    def insert_geocoding_record(self, normalized_address: str,
                                latitude: Optional[float] = None, longitude: Optional[float] = None,
                                status: str = 'pending', canonical_address: str = '', commit: bool = True) -> str:
        """Insert geocoding record. Returns UUID."""
        geocoding_id = self.generate_uuid_v7()
        self.execute_query("""
            INSERT INTO Geocoding (geocoding_id, canonical_address, normalized_address, latitude, longitude, geocoding_status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (geocoding_id, canonical_address, normalized_address, latitude, longitude, status))
        if commit:
            self.commit()
        return geocoding_id

    # Bulk operations
    def bulk_insert(self, objects: List[BaseModel], batch_size: Optional[int] = None, commit_batches: bool = True, validate_counts: bool = False, conn: Optional[duckdb.DuckDBPyConnection] = None) -> List[str]:
        if conn is None:
            with self.acquire_write_conn() as inner_conn:
                self._bulk_insert_impl(objects, inner_conn, batch_size, commit_batches, validate_counts)
        else:
            return self._bulk_insert_impl(objects, conn, batch_size, commit_batches, validate_counts)

    def _bulk_insert_impl(self, objects: List[BaseModel], conn: duckdb.DuckDBPyConnection,batch_size: Optional[int] = None, commit_batches: bool = True, validate_counts: bool = False) -> List[str]:
        """
        High-performance bulk insert with executemany and client-side UUID generation.

        This is the CORE insert method used by both GENERIC_INSERT and INSERT_BY_TYPE.
        Uses batched executemany operations for maximum throughput while maintaining
        thread safety and referential integrity.

        Args:
            objects: Non-empty same-type BaseModels (all must be same type)
            batch_size: Rows per executemany call (uses BULK_INSERT_BATCH_SIZE from constants if None)
            conn: Optional connection override (uses thread-local by default)

        Returns:
            List of str IDs (client-generated UUIDs returned in insertion order)

        Raises:
            ValueError: Invalid inputs or type mismatches
            RuntimeError: Database errors with detailed validation

        PERFORMANCE: Batched executemany with client-side UUIDs for relationship integrity
        THREADING: Uses thread-local connections for DuckDB writer safety
        VALIDATION: Count validation ensures all rows were inserted successfully
        """
        
        if not objects:
            return []
        obj_type = type(objects[0])
        if len({type(obj) for obj in objects}) > 1:
            raise ValueError("Uniform types only.")

        # Use smaller default batch size to prevent out-of-memory errors
        if batch_size is None:
            from constants import BULK_INSERT_BATCH_SIZE
            batch_size = BULK_INSERT_BATCH_SIZE if BULK_INSERT_BATCH_SIZE is not None else 10000  # Reduced from 50000
            if not isinstance(batch_size, int):
                batch_size = 10000


        # Prep all objects for insert - call prep_for_insert if method exists
        prep_start = time.perf_counter()
        prepped_count = 0
        missing_prep_types = set()
        for obj in objects:
            if hasattr(obj, 'prep_for_insert'):
                obj.prep_for_insert()
                prepped_count += 1
            else:
                missing_prep_types.add(type(obj).__name__)
            obj.set_id_if_needed()  # Generate IDs client-side for object tree relationships
        prep_time = time.perf_counter() - prep_start
        log_debug(f"Prepped {prepped_count} out of {len(objects)} objects in {prep_time:.2f}s")
        if missing_prep_types:
            log_warning(f"Objects without prep_for_insert method: {missing_prep_types}")

        # Pre-insert deduplication check for Charities - controlled by command-line parameter
        if type(objects[0]).__name__ == 'Charity' and objects and ENABLE_CHARITY_DEDUP_CHECK:
            # Collect all xml_names for batch query
            xml_names = [getattr(obj, 'xml_name', '') for obj in objects if hasattr(obj, 'xml_name') and getattr(obj, 'xml_name', '')]
            if xml_names:
                # Single query to get counts for all xml_names
                placeholders = ','.join(['?' for _ in xml_names])
                query = f"SELECT xml_name, COUNT(*) FROM Charities WHERE xml_name IN ({placeholders}) GROUP BY xml_name"
                existing_counts = dict(conn.execute(query, tuple(xml_names)).fetchall())

                # Filter objects based on batch results
                filtered_objects = []
                skipped = 0
                for obj in objects:
                    xml_name = getattr(obj, 'xml_name', '')
                    if xml_name:
                        count = existing_counts.get(xml_name, 0)
                        if count > 0:
                            skipped += 1
                            continue
                    filtered_objects.append(obj)

                if skipped > 0:
                    log_info(f"Skipped {skipped} duplicate charities in bulk insert (batch check)")
                objects = filtered_objects
                if not objects:
                    return []

        table_name = self._get_table_name(obj_type)
        model_fields = set(obj_type.get_db_field_names())
        table_cols = self._get_table_columns(table_name, conn)
        if not table_cols:
            raise ValueError(f"No table columns found for {table_name}")
        missing = set(table_cols) - model_fields
        id_field = next((col for col in table_cols if col.endswith('_id') or col == 'id'), None)
        if not id_field:
            raise ValueError(f"No ID in {table_name}.")

        # DEBUG: Log connection type and logging status
        log_info(f"DEBUG: bulk_insert called for {len(objects)} {obj_type.__name__} objects, table={table_name}")
        log_info(f"DEBUG: global_config.log_sql={global_config.log_sql}, conn type={type(conn).__name__}")
        log_info(f"DEBUG: Using LoggingDuckDBConnection: {isinstance(conn, LoggingDuckDBConnection)}")

        # COUNT VALIDATION: Check count before insert (optional for performance)
        count_before = None
        if validate_counts:
            try:
                result = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                row = result.fetchone() if result else None
                count_before = row[0] if row else None
                log_info(f"DEBUG: Count before bulk_insert: {count_before} rows in {table_name}")
            except Exception as e:
                log_warning(f"DEBUG: Could not get count before insert: {e}")
                count_before = None


        # Use all table columns including ID field since we generate them client-side
        insert_cols = table_cols


        # executemany core: Build param lists (excluding ID field)
        build_start = time.perf_counter()
        param_rows = []
        for obj in objects:
            row = tuple(getattr(obj, col) if col in model_fields else None for col in insert_cols)
            param_rows.append(row)
        build_time = time.perf_counter() - build_start
        log_debug(f"Built {len(objects)} param rows in {build_time:.2f}s")

        # Batched executemany for inserts - IDs already generated client-side
        insert_start = time.perf_counter()
        for i in range(0, len(objects), batch_size):
            batch_params = param_rows[i:i + batch_size]

            # Use executemany with single row inserts - no RETURNING needed since IDs are client-generated
            col_list = ', '.join(insert_cols)
            placeholders = ', '.join(['?' for _ in insert_cols])
            insert_sql = f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})"
            log_info(f"DEBUG: About to execute INSERT SQL: {insert_sql[:100]}...")
            log_info(f"DEBUG: Batch has {len(batch_params)} parameter sets")

            if global_config.log_sql:
                log_info(f"bulk SQL {insert_sql}")

            # SQL logging handled by execute_query method

            batch_start = time.perf_counter()
            try:
                conn.executemany(insert_sql, batch_params)  # type: ignore
            except Exception as e:
                # Check for out-of-memory errors specifically
                error_str = str(e).lower()
                if "out of memory" in error_str or "failed to offload data block" in error_str or "failed to pin" in error_str:
                    _oom_hard_exit("bulk_insert", e)
                raise
            if commit_batches:
                conn.commit()
            batch_elapsed = time.perf_counter() - batch_start
            rate = len(batch_params) / batch_elapsed if batch_elapsed > 0 else 0
            log_debug(f"Batch {i//batch_size + 1} ({len(batch_params)} rows): {batch_elapsed:.2f}s ({rate:.0f} rows/s)")
            insert_time = time.perf_counter() - insert_start
            log_info(f"executemany inserted {len(objects)} rows in {insert_time:.2f}s ({len(objects)/insert_time:.0f} rows/s)")
        total_processed = len(objects)
        conn.commit()

        # COUNT VALIDATION: Check count after insert (optional for performance)
        if validate_counts and count_before is not None:
            try:
                result = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                row = result.fetchone() if result else None
                count_after = row[0] if row else None
                log_info(f"DEBUG: Count after bulk_insert: {count_after} rows in {table_name}")
                expected_count = count_before + len(objects)
                if count_after != expected_count:
                    error_msg = f"CRITICAL: Bulk insert validation FAILED! Expected {expected_count} rows, got {count_after}. Difference: {count_after - count_before} (expected +{len(objects)})"
                    log_error(error_msg)
                    # Disable validation for performance - just log the error instead of raising
                    log_warning("Count validation disabled for performance - continuing despite validation failure")
                else:
                    log_info(f"DEBUG: Bulk insert validation PASSED: +{len(objects)} rows added")
            except Exception as e:
                log_error(f"DEBUG: Could not validate count after insert: {e}")
                if "CRITICAL" in str(e):
                    # Disable validation for performance - just log the error instead of raising
                    log_warning("Count validation disabled for performance - continuing despite validation failure")

        # Log bulk insert completion with counts
        log_info(f"Bulk insert completed: {len(objects)} {obj_type.__name__} records inserted")
        conn.commit()

        # Return the client-generated IDs
        return [str(getattr(obj, id_field)) for obj in objects]

    # wrap bulk_update to use the pool
    def bulk_update(self, table_name: str, updates: List[Dict[str, Any]], id_column: str = 'id', batch_size: int = 100, commit: bool = True, commit_batches: bool = False, conn: Optional[duckdb.DuckDBPyConnection] = None) -> int:
        if conn is None:
            with self.acquire_write_conn() as inner_conn:
                return self._bulk_update_impl(table_name, updates, id_column, batch_size, commit, commit_batches, conn=inner_conn)
        else:
            return self._bulk_update_impl(table_name, updates, id_column, batch_size, commit, commit_batches, conn=conn)

    def _bulk_update_impl(self, table_name: str, updates: List[Dict[str, Any]], id_column: str = 'id', batch_size: int = 100, commit: bool = True, commit_batches: bool = False, conn= duckdb.DuckDBPyConnection) -> int:
        """Generic bulk update — prefer UPDATE…FROM (VALUES…) for multi-row writes.

        Per-row ``executemany(UPDATE … WHERE id=?)`` blows DuckDB memory on large
        tables (Geocoding ~14M rows): ~50–100 statements hit the 7–8GB cap.
        A single ``UPDATE … FROM (VALUES …)`` per chunk stays bounded.
        """
        if not updates:
            return 0

        columns = list(updates[0].keys())
        if id_column not in columns:
            raise ValueError(f"ID column '{id_column}' not found in update data")

        set_columns = [col for col in columns if col != id_column]
        if not set_columns:
            return 0

        # Chunk size for VALUES lists (bind-param / planner balance)
        chunk = max(25, min(batch_size if batch_size and batch_size > 1 else 200, 250))

        try:
            total_processed = 0
            for i in range(0, len(updates), chunk):
                batch = updates[i:i + chunk]
                batch_start = time.perf_counter()
                try:
                    self._bulk_update_from_values(conn, table_name, batch, id_column, set_columns)
                except Exception as e:
                    error_str = str(e).lower()
                    if "out of memory" in error_str or "failed to offload data block" in error_str or "failed to pin" in error_str:
                        _oom_hard_exit("bulk_update", e)
                    # Fallback: legacy per-row path for exotic types / planner rejects
                    log_warning(f"UPDATE FROM VALUES failed ({e}); falling back to executemany for {len(batch)} rows")
                    set_clause = ", ".join([f"{col} = ?" for col in set_columns])
                    sql = f"UPDATE {table_name} SET {set_clause} WHERE {id_column} = ?"
                    params = [
                        tuple([row[col] for col in set_columns] + [row[id_column]])
                        for row in batch
                    ]
                    try:
                        conn.executemany(sql, params)  # type: ignore
                    except Exception as e2:
                        error_str2 = str(e2).lower()
                        if "out of memory" in error_str2 or "failed to offload data block" in error_str2 or "failed to pin" in error_str2:
                            _oom_hard_exit("bulk_update", e2)
                        raise
                if commit_batches:
                    conn.commit()
                batch_elapsed = time.perf_counter() - batch_start
                rate = len(batch) / batch_elapsed if batch_elapsed > 0 else 0
                log_debug(
                    f"Bulk UPDATE FROM chunk {i//chunk + 1} ({len(batch)} rows) "
                    f"{table_name}: {batch_elapsed:.2f}s ({rate:.0f} rows/s)"
                )
                total_processed += len(batch)

            if commit and not commit_batches:
                conn.commit()
            elif commit and commit_batches:
                try:
                    conn.commit()
                except Exception:
                    pass

            return total_processed
        except Exception as e:
            raise RuntimeError(f"Bulk update failed for table {table_name}: {str(e)}") from e

    def _bulk_update_from_values(
        self,
        conn,
        table_name: str,
        updates: List[Dict[str, Any]],
        id_column: str,
        set_columns: List[str],
    ) -> None:
        """One UPDATE…FROM (VALUES…) for a homogeneous column set."""
        # Stable SQL identifiers for source columns
        src_cols = [id_column] + set_columns
        aliases = [f"s_{i}" for i in range(len(src_cols))]
        alias_by_col = dict(zip(src_cols, aliases))

        value_rows = []
        flat_params: List[Any] = []
        for row in updates:
            value_rows.append("(" + ", ".join(["?"] * len(src_cols)) + ")")
            for col in src_cols:
                flat_params.append(row[col])

        set_sql = ", ".join(
            f"{col} = src.{alias_by_col[col]}" for col in set_columns
        )
        values_sql = ", ".join(value_rows)
        alias_list = ", ".join(aliases)
        sql = (
            f"UPDATE {table_name} AS tgt SET {set_sql} "
            f"FROM (VALUES {values_sql}) AS src({alias_list}) "
            f"WHERE tgt.{id_column} = src.{alias_by_col[id_column]}"
        )
        conn.execute(sql, flat_params)

    def get_bulk_operations(self):
        """Get bulk operations handler"""
        # DuckDB handles bulk operations internally
        return self

    def get_xml_files_to_process(self, processing_version: int, max_files: Optional[int] = None, last_xml_id: Optional[str] = None) -> List[XMLFile]:
        """Get unprocessed XML files with key-value paging support"""
        where_clause = "processed = FALSE"
        params = ()
        if last_xml_id:
            where_clause += " AND xml_id > ?"
            params += (last_xml_id,)
        order_by = "xml_id"
        limit = max_files

        # DEBUG: Log query details
        log_info("DEBUG: get_xml_files_to_process - processing_version={}, max_files={}, last_xml_id={}", processing_version, max_files, last_xml_id)
        log_info("DEBUG: Query: WHERE {}, ORDER BY {}, LIMIT {}", where_clause, order_by, limit)
        log_info("DEBUG: Params: {}", params)

        result = self.select_dataclass(XMLFile, where_clause=where_clause, params=params, order_by=order_by, limit=limit)
        log_info("DEBUG: Query returned {} XML files", len(result))
        return result

    def get_xml_files_to_process_count(self, processing_version: int, mode: str = 'count', max_files: Optional[int] = None) -> Union[int, float]:
        """
        Get the count or total bytes of unprocessed XML files.

        Args:
            processing_version: Processing version to filter by
            mode: 'count' for file count, 'bytes' for total file size sum
            max_files: Optional limit for testing (affects both count and sum)

        Returns:
            int for count mode, float for bytes mode (sum of file_size)
        """
        base_where = "processed = FALSE"
        base_params = []

        # DEBUG: Log count query details
        log_info(f"DEBUG: get_xml_files_to_process_count - processing_version={processing_version}, mode={mode}, max_files={max_files}")
        
        if mode == 'bytes':
            if max_files is not None:
                subquery = f"""
                    SELECT file_size FROM XmlFiles
                    WHERE {base_where}
                    ORDER BY xml_id
                    LIMIT ?
                """
                params = base_params + [max_files]
                query = f"SELECT COALESCE(SUM(file_size), 0) FROM ({subquery})"
            else:
                query = f"""
                    SELECT COALESCE(SUM(file_size), 0) FROM XmlFiles
                    WHERE {base_where}
                """
                params = base_params
        else:  # 'count'
            if max_files is not None:
                # For count with limit, the count is min(actual_count, max_files)
                # But to be precise, query the limited count
                subquery = f"""
                    SELECT 1 FROM XmlFiles
                    WHERE {base_where}
                    ORDER BY xml_id
                    LIMIT ?
                """
                params = base_params + [max_files]
                query = f"SELECT COUNT(*) FROM ({subquery})"
            else:
                query = f"SELECT COUNT(*) FROM XmlFiles WHERE {base_where}"
                params = base_params
        
        result = self.execute_query(query, tuple(params))
        count = result.fetchone()[0] if result else 0
        log_info(f"DEBUG: get_xml_files_to_process_count returned {count}")
        log_info(f"DEBUG: Query was: {query}")
        log_info(f"DEBUG: Params were: {params}")
        return count

    # Context-based approach handles this now

    # Export operations
    def get_export_operations(self, final_dir: str):
        """Get export operations handler"""
        # DuckDB handles export operations through its own methods
        return self

    def get_stats_processor(self):
        """Get stats processor instance"""
        from stats_processor import StatsProcessor
        return StatsProcessor(self)

    def optimize_database(self, commit: bool = True):
        """Run database optimization commands with macOS-compatible checkpointing.

        Uses conn.execute directly (not execute_query) so OOM on VACUUM ANALYZE
        does not sys.exit the whole pipeline after a successful step.
        """
        log_info("Starting database optimization...")
        with self.acquire_write_conn() as conn:

            # Prefer ANALYZE-only first (cheap); VACUUM ANALYZE can OOM on huge tables.
            tables_to_optimize = ["Charities","Grants","Addresses","Officers","Geocoding","Backfill","XmlFiles","Contributions","Contractors","PoliticalContributions"]
            for table in tables_to_optimize:
                log_debug(f"Optimizing table: {table}")
                try:
                    conn.execute(f"ANALYZE {table}")
                    log_debug(f"Successfully ANALYZE {table}")
                except Exception as e:
                    log_warning(f"Failed to ANALYZE {table}: {e}")

            # Ensure any pending changes are committed before checkpoint
            if commit:
                try:
                    conn.commit()
                except Exception as e:
                    log_warning(f"Commit before checkpoint failed: {e}")
            
            # Now attempt CHECKPOINT for WAL flushing and performance benefits
            log_info("Performing database checkpoint for WAL cleanup...")
            try:
                conn.execute("CHECKPOINT")
                log_info("Database checkpoint completed successfully")
            except Exception as e:
                log_warning(f"Checkpoint failed even after connection recycling: {e}")
                # Continue anyway - the recycling itself provides some WAL cleanup

            if commit:
                try:
                    conn.commit()
                except Exception as e:
                    log_warning(f"Final commit after optimize failed: {e}")

    # Logging methods removed - use global logging functions directly

    def _execute_optimize_operation(self, operation, conn):
        """Execute database optimization operation"""
        if operation.operation_type != DatabaseOperationType.OPTIMIZE_DATABASE:
            return

        log_info("Starting database optimization...")
        try:
            # Call the optimize_database method from DatabaseOperations
            self.optimize_database()
            log_info("Database optimization completed successfully")
        except Exception as e:
            log_error(f"Database optimization failed: {e}", exc_info=True)
            raise

    # All processing methods removed - context-based approach handles this now

    def _process_xml_file_update_operations(self, operations_by_type, conn, processed_xml_ids):
        """Process XML file update operations using metadata"""
        if DatabaseOperationType.XML_FILE_UPDATE.value not in operations_by_type:
            return

        xml_updates = operations_by_type[DatabaseOperationType.XML_FILE_UPDATE.value]  # type: ignore

        for operation in xml_updates:
            xml_id = operation.xml_id
            metadata = operation.data

            try:
                self._update_xml_file_with_metadata(xml_id, metadata, conn)
                processed_xml_ids.add(xml_id)
            except Exception as e:
                log_error(f"Failed to update XML file {xml_id} with metadata: {e}")
                # Do not raise here - continue processing other XML files

    def _process_charity_operations(self, operations_by_type, conn):
        """Process charity insert operations and return charity_id mapping"""
        charity_id_map = {}  # xml_id -> charity_id

        if DatabaseOperationType.INSERT_CHARITY.value not in operations_by_type:
            return charity_id_map

        charities = [op.data for op in operations_by_type[DatabaseOperationType.INSERT_CHARITY.value]]  # type: ignore

        if not charities:
            return charity_id_map

        log_info(f"Bulk insert: Processing {len(charities)} charities")

        # Set colocator to 'notyet' for new charities
        for charity in charities:
            charity.colocator = 'notyet'

        try:
            # Use database_operations bulk_insert method which calls prep_for_insert
            ids = self.bulk_insert(charities, conn=conn)
            log_info(f"Bulk insert: Inserted {len(charities)} charities")

            # Map xml_id to charity_id using the operations list and returned IDs
            charity_ops = operations_by_type[DatabaseOperationType.INSERT_CHARITY.value]  # type: ignore
            for i, charity_id in enumerate(ids):
                if i < len(charity_ops):
                    xml_id = charity_ops[i].xml_id
                    charity_id_map[xml_id] = charity_id

        except Exception as e:
            log_error(f"Failed to insert charities: {e}", exc_info=True)
            raise

        return charity_id_map


    def _process_address_operations(self, operations_by_type, conn, charity_id_map):
        """Process address insert operations"""

        if DatabaseOperationType.INSERT_ADDRESS.value not in operations_by_type:
            return

        addresses = []
        for operation in operations_by_type[DatabaseOperationType.INSERT_ADDRESS.value]:  # type: ignore
            address = operation.data

            # Set owner_id for charity addresses (link to charity that owns this address)
            if hasattr(address, 'address_type') and address.address_type == 'charity':
                if operation.xml_id in charity_id_map:
                    address.owner_id = charity_id_map[operation.xml_id]

            addresses.append(address)

        if addresses:
            try:
                # Use database_operations bulk_insert method which calls prep_for_insert
                ids = self.bulk_insert(addresses, conn=conn)
                log_debug(f"Inserted {len(addresses)} addresses")
            except Exception as e:
                log_error(f"Failed to insert addresses: {e}", exc_info=True)

    def format_error_with_traceback(self, error: Exception, context: str = "") -> str:
        """Format error message with full stack trace for better debugging"""
        import traceback
        error_msg = f"{context}: {str(error)}" if context else str(error)
        stack_trace = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        return f"{error_msg}\n\nStack Trace:\n{stack_trace}"

    def _get_xml_files_updated_in_batch(self, batch_operations):
        """Get set of XML IDs that were updated in this batch (XML_FILE_UPDATE operations)"""
        xml_files_updated = set()
        for op in batch_operations:
            if op.operation_type == DatabaseOperationType.XML_FILE_UPDATE:
                xml_files_updated.add(op.xml_id)
        return xml_files_updated

    def get_address_deduplication_batch(self, last_address_id: Optional[str] = None, limit: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Get canonical addresses that have duplicates needing deduplication with key-value pagination.

        Optimized single-phase query approach using master address_ids for efficient IN() queries:
        - Collects all address_ids and master_ids for qualifying canonical addresses in one query
        - Uses LIST aggregates to collect address data efficiently
        - Avoids the expensive Phase 2 query by processing master/child logic directly from collected data

        Returns canonical addresses where there are multiple addresses with the same canonical_address,
        and at least one of them has master_id IS NULL (not yet deduplicated).

        Args:
            last_address_id: Last address_id from previous batch for key-value pagination
            limit: Maximum number of canonical addresses to return

        Returns a tuple of:
        - List of deduplication operations, each containing master and children info
        - Next last_address_id for pagination (maximum of the minimum address_ids from master addresses)

        Returns:
            Tuple of (batch_operations, next_last_address_id)
        """
        import time
        start_time = time.time()

        batch_limit = limit or 1000  # Default limit if not specified

        # Single optimized query: Collect all address_ids and master_ids for qualifying canonical addresses
        # Use key-value pagination with min_id > last_address_id
        where_clause = ""
        params = []
        if last_address_id is not None:
            where_clause = "WHERE min_id > ?"
            params = [last_address_id]

        # Use LIST aggregates to collect all address_ids and master_ids for each canonical_address
        # This allows us to determine master/child relationships without a separate Phase 2 query
        optimized_query = f"""
            SELECT
                canonical_address,
                min_id,
                address_ids,
                master_ids
            FROM (
                SELECT
                    canonical_address,
                    MIN(address_id) as min_id,
                    LIST(address_id ORDER BY address_id) as address_ids,
                    LIST(master_id ORDER BY address_id) as master_ids
                FROM Addresses
                WHERE canonical_address IS NOT NULL
                    AND canonical_address != ''
                GROUP BY canonical_address
                HAVING COUNT(*) > 1
                    AND SUM(CASE WHEN master_id IS NULL THEN 1 ELSE 0 END) > 1
            ) sub
            {where_clause}
            ORDER BY min_id
            LIMIT ?
        """
        params.append(str(batch_limit))

        query_start = time.time()
        result = self.execute_query(optimized_query, tuple(params))
        rows = result.fetchall() if result else []
        query_time = time.time() - query_start

        log_debug(f"Optimized query: Found {len(rows)} qualifying canonical addresses in {query_time:.2f}s")

        if not rows:
            return [], None

        # Calculate next last_address_id as the maximum of the min_id values from this batch
        next_last_address_id = max(row[1] for row in rows if row[1] is not None) if rows else None

        # Process collected data to build batch operations
        # address_ids and master_ids are returned as lists from LIST aggregate
        batch_operations = []
        for row in rows:
            canonical_address = str(row[0]) if row[0] is not None else ''
            min_id = row[1]
            address_ids = row[2] if row[2] is not None else []
            master_ids = row[3] if row[3] is not None else []

            if not address_ids or len(address_ids) != len(master_ids):
                continue  # Skip invalid data

            # Find addresses with NULL master_id (candidates for children)
            null_master_indices = [i for i, master_id in enumerate(master_ids) if master_id is None]

            if len(null_master_indices) <= 1:
                continue  # Need more than one NULL master_id to deduplicate

            # Get address_ids for NULL master_id addresses
            null_master_address_ids = [address_ids[i] for i in null_master_indices]

            # Use the maximum address_id among NULL master_id addresses as master
            master_address_id = max(null_master_address_ids)

            # Children are the other NULL master_id addresses
            child_address_ids = [addr_id for addr_id in null_master_address_ids if addr_id != master_address_id]

            if child_address_ids:  # Only include if there are children to update
                batch_operations.append({
                    'canonical_address': canonical_address,
                    'master_address_id': master_address_id,
                    'child_address_ids': child_address_ids
                })

        total_time = time.time() - start_time
        log_debug(f"Total optimized batch processing time: {total_time:.2f}s")
        self.commit()

        return batch_operations, next_last_address_id

    def execute_address_deduplication_batch(self, master_address_id: str, child_address_ids: List[str], commit: bool = True, conn=None) -> int:
        """
        Execute a batch of address deduplication updates.

        Updates all child addresses to point to the master address, including
        self-updating the master address itself to ensure no NULL master_id on roots.
        Also propagates geocoding_id from master to children to avoid redundant geocoding.

        Uses bulk_update to prevent write-write conflicts within transactions.

        Args:
            master_address_id: The address_id of the master address
            child_address_ids: List of address_ids that should point to the master (may include master)

        Returns:
            Number of addresses updated
        """
        if not child_address_ids:
            return 0

        # Get the master's geocoding_id, colocator, and current master_id to propagate to children
        master_info = self.execute_query("""
            SELECT geocoding_id, colocator, master_id FROM Addresses WHERE address_id = ?
        """, (master_address_id,)).fetchone()

        master_geocoding_id = master_info[0] if master_info else None
        master_colocator = master_info[1] if master_info else None
        master_current_master_id = master_info[2] if master_info else None

        # Build bulk update data - each address gets updated exactly once
        updates = []

        # Check if master address already has correct master_id (may have been set by geocoding operation)
        if master_current_master_id != master_address_id:
            # Master address update only if not already set correctly
            master_update = {
                'address_id': master_address_id,
                'master_id': master_address_id
            }
            updates.append(master_update)

        # Child address updates
        for child_id in child_address_ids:
            if child_id != master_address_id:  # Avoid duplicate update for master
                child_update = {
                    'address_id': child_id,
                    'master_id': master_address_id
                }
                if master_geocoding_id is not None:
                    child_update['geocoding_id'] = master_geocoding_id
                updates.append(child_update)

        # Deduplicate updates by address_id to prevent conflicts if same address appears multiple times
        updates_by_id = {}
        for update in updates:
            updates_by_id[update['address_id']] = update
        deduplicated_updates = list(updates_by_id.values())

        # Execute bulk update to prevent write-write conflicts
        updated_count = self.bulk_update('Addresses', deduplicated_updates, id_column='address_id', commit=False, conn=conn)

        if commit:
            self.commit()

        return updated_count

    def execute_operation(self, operation: DatabaseOperation, conn=None):
        """Execute a single database operation"""
        if operation.operation_type == DatabaseOperationType.XML_FILE_UPDATE:
            self._execute_xml_file_update_operation(operation, conn)
        elif operation.operation_type == DatabaseOperationType.UPDATE_XML_EIN:
            self.execute_update_xml_ein_operation(operation, conn)
        elif operation.operation_type == DatabaseOperationType.OPTIMIZE_DATABASE:
            self._execute_optimize_operation(operation, conn)
        elif operation.operation_type == DatabaseOperationType.GENERIC_UPDATE:
            self._execute_generic_update_operation(operation, conn)
        else:
            log_warning("Unknown operation type: {}", operation.operation_type)

    def _execute_xml_file_update_operation(self, operation: DatabaseOperation):
        """Execute XML_FILE_UPDATE operation"""
        with self.acquire_write_conn() as conn:

            xml_id = operation.xml_id
            metadata = operation.data

            # Update the XML file with metadata
            update_fields = []
            params = []

            if 'processed' in metadata:
                update_fields.append("processed = ?")
                params.append(metadata['processed'])

            if 'processing_version' in metadata:
                update_fields.append("processing_version = ?")
                params.append(metadata['processing_version'])

            if 'error_message' in metadata:
                update_fields.append("error_message = ?")
                params.append(metadata['error_message'])

            if 'ein' in metadata:
                update_fields.append("ein = ?")
                params.append(metadata['ein'])

            # Always update processed_at
            update_fields.append("processed_at = ?")
            params.append(datetime.now().isoformat())

            if update_fields:
                query = f"UPDATE XmlFiles SET {', '.join(update_fields)} WHERE xml_id = ?"
                params.append(xml_id)
                conn.execute(query, tuple(params))
                conn.commit()

    def _try_where_update_from_values(
        self,
        conn,
        table_name: str,
        set_clause: str,
        where_clause: str,
        param_sets: List[Any],
    ) -> bool:
        """Rewrite multi-param WHERE updates as one UPDATE…FROM (VALUES…).

        Handles the census colocator pattern:
          SET colocator = ?, latitude = COALESCE(latitude, ?), longitude = COALESCE(longitude, ?)
          WHERE geocoding_id = ? AND (colocator IS NULL OR TRIM(colocator) = '')

        Returns True if executed, False to fall back to executemany.
        """
        if not param_sets or len(param_sets) < 5:
            return False

        # Only support simple patterns we can rewrite safely
        where_norm = " ".join(where_clause.split()).lower()
        set_norm = " ".join(set_clause.split()).lower()

        # Addresses colocator propagation (primary OOM source during census)
        is_addr_colocator = (
            table_name.lower() == "addresses"
            and "geocoding_id = ?" in where_norm
            and "colocator = ?" in set_norm
        )
        if not is_addr_colocator:
            return False

        # Infer param layout from first row: trailing param is geocoding_id
        n = len(param_sets[0])
        if n < 2:
            return False

        # Build VALUES rows — all params preserved in order as p0..p{n-1}
        # Rewrite SET/WHERE to use src.p* with table-qualified COALESCE targets
        # Map: set_clause uses ? in order; where uses remaining ?
        # We assign: p0..p{n-2} for SET side (rewritten), p{n-1} = geocoding_id
        try:
            # Count ? in set vs where
            n_set = set_clause.count("?")
            n_where = where_clause.count("?")
            if n_set + n_where != n:
                return False

            # For known Addresses pattern rewrite explicitly when shapes match
            has_lat = "latitude" in set_norm
            has_lon = "longitude" in set_norm
            if has_lat and has_lon and n == 4:
                # params: colocator, lat, lon, gid
                value_rows = []
                flat: List[Any] = []
                for ps in param_sets:
                    value_rows.append("(?, ?, ?, ?)")
                    flat.extend(list(ps))
                values_sql = ", ".join(value_rows)
                sql = f"""
                    UPDATE Addresses AS a
                    SET
                        colocator = v.colocator,
                        latitude = COALESCE(a.latitude, v.lat),
                        longitude = COALESCE(a.longitude, v.lon)
                    FROM (VALUES {values_sql}) AS v(colocator, lat, lon, gid)
                    WHERE a.geocoding_id = v.gid
                      AND (a.colocator IS NULL OR TRIM(a.colocator) = '')
                """
                # Chunk large lists
                chunk = 200
                for i in range(0, len(param_sets), chunk):
                    part = param_sets[i:i + chunk]
                    flat_part: List[Any] = []
                    rows = []
                    for ps in part:
                        rows.append("(?, ?, ?, ?)")
                        flat_part.extend(list(ps))
                    sql_part = f"""
                        UPDATE Addresses AS a
                        SET
                            colocator = v.colocator,
                            latitude = COALESCE(a.latitude, v.lat),
                            longitude = COALESCE(a.longitude, v.lon)
                        FROM (VALUES {', '.join(rows)}) AS v(colocator, lat, lon, gid)
                        WHERE a.geocoding_id = v.gid
                          AND (a.colocator IS NULL OR TRIM(a.colocator) = '')
                    """
                    conn.execute(sql_part, flat_part)
                log_info(f"WHERE UPDATE FROM VALUES Addresses colocator: {len(param_sets)} gids")
                return True

            if not has_lat and not has_lon and n == 2:
                # params: colocator, gid
                chunk = 200
                for i in range(0, len(param_sets), chunk):
                    part = param_sets[i:i + chunk]
                    flat_part = []
                    rows = []
                    for ps in part:
                        rows.append("(?, ?)")
                        flat_part.extend(list(ps))
                    sql_part = f"""
                        UPDATE Addresses AS a
                        SET colocator = v.colocator
                        FROM (VALUES {', '.join(rows)}) AS v(colocator, gid)
                        WHERE a.geocoding_id = v.gid
                          AND (a.colocator IS NULL OR TRIM(a.colocator) = '')
                    """
                    conn.execute(sql_part, flat_part)
                log_info(f"WHERE UPDATE FROM VALUES Addresses colocator-only: {len(param_sets)} gids")
                return True
        except Exception as e:
            err = str(e).lower()
            if "out of memory" in err or "failed to offload" in err or "failed to pin" in err:
                _oom_hard_exit("where_update_from_values", e)
            log_warning(f"WHERE UPDATE FROM VALUES failed, will fall back: {e}")
            return False

        return False

    def _execute_generic_update_operation(self, operation: DatabaseOperation, conn: Optional[duckdb.DuckDBPyConnection] = None):
        if conn is None:
            with self.acquire_write_conn() as inner_conn:
                self._execute_generic_update_operation_impl(operation, conn=inner_conn)
        else:
            self._execute_generic_update_operation_impl(operation, conn=conn)
        
        
    def _execute_generic_update_operation_impl(self, operation: DatabaseOperation, conn: duckdb.DuckDBPyConnection):
        """Execute GENERIC_UPDATE operation"""

        data = operation.data
        if not data or 'table' not in data:
            log_error("GENERIC_UPDATE operation missing required data: table")
            return

        table_name = data['table']

        # Check if this is a WHERE clause update (optimization for address deduplication)
        where_clause = data.get('where_clause')
        if where_clause:
            # WHERE clause update - direct query execution
            set_clause = data.get('set_clause', '')
            params = data.get('params', [])
            param_sets = data.get('param_sets', [])  # Batched parameter sets

            if not set_clause:
                log_error("GENERIC_UPDATE with where_clause missing set_clause")
                return

            query = f"UPDATE {table_name} SET {set_clause} WHERE {where_clause}"
            updated_count = 0
            try:
                if param_sets:
                    # Prefer a single UPDATE…FROM for geocoding colocator propagation
                    # (was 430× executemany → OOM at 7.4GB). Fall back to small batches.
                    if self._try_where_update_from_values(
                        conn, table_name, set_clause, where_clause, param_sets
                    ):
                        updated_count = len(param_sets) * 5
                        log_debug(
                            f"Executed WHERE UPDATE FROM VALUES: {len(param_sets)} ops "
                            f"on {table_name}"
                        )
                    else:
                        from constants import BULK_UPDATE_BATCH_SIZE
                        batch_size = BULK_UPDATE_BATCH_SIZE if BULK_UPDATE_BATCH_SIZE is not None else 10
                        if not isinstance(batch_size, int):
                            batch_size = 10
                        # Smaller batches + optional mid-commit when many param sets
                        if len(param_sets) > 50:
                            batch_size = min(batch_size, 15)

                        total_updated_count = 0
                        for i in range(0, len(param_sets), batch_size):
                            batch_params = param_sets[i:i + batch_size]
                            conn.executemany(query, batch_params)
                            batch_updated_count = len(batch_params) * 5
                            total_updated_count += batch_updated_count
                            log_debug(
                                f"Executed batched WHERE UPDATE batch {i//batch_size + 1}: "
                                f"{len(batch_params)} operations, ~{batch_updated_count} rows "
                                f"updated in {table_name}"
                            )
                            # Free WAL/memory mid-flight for large WHERE storms
                            if len(param_sets) > 80 and (i // batch_size) % 5 == 4:
                                try:
                                    conn.commit()
                                    conn.execute("CHECKPOINT")
                                    conn.execute("BEGIN TRANSACTION")
                                except Exception as mid_e:
                                    err = str(mid_e).lower()
                                    if "out of memory" in err or "failed to offload" in err:
                                        _oom_hard_exit("generic_update/mid_checkpoint", mid_e)

                        updated_count = total_updated_count
                        log_debug(
                            f"Executed total batched WHERE UPDATE: {len(param_sets)} operations, "
                            f"~{updated_count} rows updated in {table_name}"
                        )
                else:
                    # Single parameter set
                    result = conn.execute(query, tuple(params))
                    updated_count = result.rowcount if hasattr(result, 'rowcount') else 0
                    log_debug(f"Executed WHERE UPDATE: {updated_count} rows updated in {table_name}")
            except Exception as e:
                # Check for out-of-memory errors specifically
                error_str = str(e).lower()
                if "out of memory" in error_str or "failed to offload data block" in error_str or "failed to pin" in error_str:
                    _oom_hard_exit("generic_update", e)
                log_error(f"Failed to execute WHERE UPDATE for table {table_name}: {e}", exc_info=True)
                raise
        else:
            # Traditional bulk update by ID
            if 'updates' not in data:
                log_error("GENERIC_UPDATE operation missing required data: updates")
                return

            updates = data['updates']
            id_column = data.get('id_column', 'id')

            if not updates:
                log_debug(f"No updates to perform for table {table_name}")
                return

            updated_count = 0
            try:
                updated_count = self.bulk_update(table_name, updates, id_column=id_column, conn=conn, commit=False)
                log_debug(f"Executed GENERIC_UPDATE: {updated_count} rows updated in {table_name}")
            except Exception as e:
                log_error(f"Failed to execute GENERIC_UPDATE for table {table_name}: {e}", exc_info=True)
                raise

    def get_officers_for_export_batch(self, offset: int, limit: int) -> List[Tuple]:
        """Get batch of officers for export"""
        query = """
            SELECT charity_id, first_name, last_name, compensation, tax_year, photo_url
            FROM Officers
            ORDER BY charity_id, last_name, first_name
            LIMIT ? OFFSET ?
        """
        result = self.execute_query(query, (limit, offset))
        return result.fetchall() if result else []
    
    def _flush_and_checkpoint(self, conn, updated_so_far: int) -> int:
        """Safely commit + FORCE CHECKPOINT + restart transaction — the ONLY way that works mid-batch"""
        try:
            conn.commit()                                   # End current huge transaction
            conn.execute("PRAGMA force_checkpoint")        # The magic command that never hangs or complains
            conn.execute("BEGIN TRANSACTION")               # Fresh start
            log_info(f"✓ FORCE CHECKPOINT completed after ~{updated_so_far:,} address updates — memory/WAL reset")
            return 0  # reset counter
        except Exception as e:
            log_warning(f"Flush/checkpoint failed (continuing): {e}")
            try:
                conn.execute("BEGIN TRANSACTION")
            except:
                pass
            return 0

    def _intermediate_commit_and_checkpoint(self, conn, updated_so_far: int) -> int:
        """Commit + force checkpoint + restart transaction — the only sequence that actually frees memory on macOS"""
        try:
            print("Doing intermediate checkpoint")
            conn.commit()                                # Ends current transaction cleanly
            conn.execute("CHECKPOINT")                   # Normal CHECKPOINT now works (no active tx)
            conn.execute("BEGIN TRANSACTION")            # Start fresh
            log_info(f"INTERMEDIATE CHECKPOINT after ~{updated_so_far:,} address updates — memory/WAL freed")
            return 0
        except Exception as e:
            log_warning(f"Intermediate checkpoint failed (continuing anyway): {e}")
            try:
                conn.execute("BEGIN TRANSACTION")
            except:
                pass
            return 0
        
    def update_authoritative_ein(self, name: str, colocator: str, ein: str):
        """Insert or update AuthoritativeEin with conflict handling."""
        self.execute_query("""
            INSERT INTO AuthoritativeEin (name, colocator, ein, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT (name, colocator) 
            DO UPDATE SET 
                ein = excluded.ein,
                count = AuthoritativeEin.count + 1
        """, [name, colocator, ein])
        
    def get_charities_for_ratio_computation(self, last_charity_id: Optional[str] = None, limit: int = 5000) -> Tuple[List[Tuple], Optional[str]]:
        """Get batch of charities needing denominator/_pct computation (keyset pagination)"""
        where = "denominator IS NULL OR denominator = 0"
        if last_charity_id:
            where += " AND charity_id > ?"
            params = (last_charity_id, limit)
        else:
            params = (limit,)

        query = f"""
            SELECT charity_id, receipt_amt, total_exp, officer_comp, travel_amt, 
                conferences_amt, grants_to_others, foreign_expenses
            FROM Charities
            WHERE {where}
            ORDER BY charity_id
            LIMIT ?
        """
        result = self.execute_query(query, params)
        rows = result.fetchall()
        last_id = rows[-1][0] if rows else None
        return rows, last_id

def update_charity_ratios(self, charity_id: str, denominator: Optional[float],
                          comp_pct: Optional[float], travel_pct: Optional[float],
                          conferences_pct: Optional[float], grants_pct: Optional[float],
                          foreign_expenses_pct: Optional[float]):
    """Update denominator + _pct columns"""
    self.execute_query("""
        UPDATE Charities SET
            denominator = ?,
            comp_pct = ?,
            travel_pct = ?,
            conferences_pct = ?,
            grants_pct = ?,
            foreign_expenses_pct = ?
        WHERE charity_id = ?
    """, (denominator, comp_pct, travel_pct, conferences_pct, grants_pct, foreign_expenses_pct, charity_id))
    self.commit()

def get_charity_groups_for_percentiles(self, last_org_type: Optional[str] = None, 
                                        last_tax_year: Optional[int] = None, 
                                        limit: int = 50) -> List[Tuple]:
    """Get (org_type, tax_year) groups that need _ptile computation (keyset pagination on groups)"""
    where = "denominator > 0 AND comp_ptile IS NULL"
    params = []
    if last_org_type and last_tax_year:
        where += " AND (org_type > ? OR (org_type = ? AND tax_year > ?))"
        params = [last_org_type, last_org_type, last_tax_year]
    params.append(limit)

    query = f"""
        SELECT DISTINCT org_type, tax_year
        FROM Charities
        WHERE {where}
        ORDER BY org_type, tax_year
        LIMIT ?
    """
    result = self.execute_query(query, tuple(params))
    return result.fetchall()

def compute_percentiles_for_group(self, org_type: str, tax_year: int):
    """Compute _ptile columns for a single (org_type, tax_year) group using pure SQL"""
    sql = """
        WITH ranked AS (
            SELECT 
                charity_id,
                PERCENT_RANK() OVER (ORDER BY comp_pct) * 100 AS comp_ptile,
                PERCENT_RANK() OVER (ORDER BY travel_pct) * 100 AS travel_ptile,
                PERCENT_RANK() OVER (ORDER BY conferences_pct) * 100 AS conferences_ptile,
                PERCENT_RANK() OVER (ORDER BY grants_pct) * 100 AS grants_ptile,
                PERCENT_RANK() OVER (ORDER BY foreign_expenses_pct) * 100 AS foreign_expenses_ptile
            FROM Charities
            WHERE org_type = ? AND tax_year = ? AND denominator > 0
        )
        UPDATE Charities c
        SET 
            comp_ptile = r.comp_ptile,
            travel_ptile = r.travel_ptile,
            conferences_ptile = r.conferences_ptile,
            grants_ptile = r.grants_ptile,
            foreign_expenses_ptile = r.foreign_expenses_ptile
        FROM ranked r
        WHERE c.charity_id = r.charity_id
    """
    self.execute_query(sql, (org_type, tax_year))
    self.commit()
    
def get_charities_for_ratio_computation(self, last_charity_id: Optional[str] = None, 
                                            limit: int = 5000) -> Tuple[List[Charity], Optional[str]]:
        """Get batch of charities needing denominator/_pct computation (keyset pagination via where_clause)"""
        where_clause = "denominator IS NULL OR denominator = 0"
        params = ()
        if last_charity_id:
            where_clause += " AND charity_id > ?"
            params = (last_charity_id,)

        charities = self.select_dataclass(
            Charity,
            where_clause=where_clause,
            params=params,
            order_by="charity_id",
            limit=limit
        )

        last_id = charities[-1].charity_id if charities else None
        return charities, last_id

def get_charity_groups_for_percentiles(self, last_org_type: Optional[str] = None,
                                        last_tax_year: Optional[int] = None,
                                        limit: int = 50) -> List[Tuple[str, int]]:
    """Get distinct (org_type, tax_year) groups needing _ptile computation (keyset pagination)"""
    where_clause = "denominator > 0 AND comp_ptile IS NULL"
    params = []
    if last_org_type and last_tax_year:
        where_clause += " AND (org_type > ? OR (org_type = ? AND tax_year > ?))"
        params = [last_org_type, last_org_type, last_tax_year]

    query = f"""
        SELECT DISTINCT org_type, tax_year
        FROM Charities
        WHERE {where_clause}
        ORDER BY org_type, tax_year
        LIMIT ?
    """
    params.append(limit)
    result = self.execute_query(query, tuple(params))
    return result.fetchall()

def get_charities_for_percentile_group(self, org_type: str, tax_year: int) -> List[Charity]:
    """Get all charities in a specific (org_type, tax_year) group for percentile computation"""
    where_clause = "org_type = ? AND tax_year = ? AND denominator > 0"
    return self.select_dataclass(
        Charity,
        where_clause=where_clause,
        params=(org_type, tax_year),
        order_by="charity_id"
    )

def update_charity_ratios(self, charity_id: str, denominator: Optional[float],
                            comp_pct: Optional[float], travel_pct: Optional[float],
                            conferences_pct: Optional[float], grants_pct: Optional[float],
                            foreign_expenses_pct: Optional[float]):
    """Update denominator + _pct columns for a single charity"""
    self.execute_query("""
        UPDATE Charities SET
            denominator = ?,
            comp_pct = ?,
            travel_pct = ?,
            conferences_pct = ?,
            grants_pct = ?,
            foreign_expenses_pct = ?
        WHERE charity_id = ?
    """, (denominator, comp_pct, travel_pct, conferences_pct, grants_pct, foreign_expenses_pct, charity_id))
    self.commit()

def get_last_processed_charity_id(self) -> Optional[str]:
    """Helper: find the highest charity_id that already has a denominator set (for auto-resume)"""
    result = self.execute_query("SELECT MAX(charity_id) FROM Charities WHERE denominator IS NOT NULL")
    row = result.fetchone() if result else None
    return row[0] if row and row[0] else None

def get_last_processed_group(self) -> Optional[Tuple[str, int]]:
    """Helper: find the last (org_type, tax_year) that has _ptile values (for auto-resume)"""
    result = self.execute_query("""
        SELECT org_type, tax_year
        FROM Charities
        WHERE comp_ptile IS NOT NULL
        ORDER BY org_type DESC, tax_year DESC
        LIMIT 1
    """)
    row = result.fetchone() if result else None
    return (row[0], row[1]) if row else None

    