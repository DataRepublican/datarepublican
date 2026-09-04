#!/usr/bin/env python3
"""
pending_database_context.py - Context object for collecting database objects during XML parsing

This module provides a PendingDatabaseContext class that collects all objects
to be inserted into the database, eliminating the need for tuple passing
through the parse tree.

ARCHITECTURE OVERVIEW:
- PendingDatabaseContext (PDC): Collects database objects during processing
- Eliminates tuple passing through parse trees
- Handles ownership relationships and operation execution
- Integrates with DatabaseOperations for bulk inserts

KEY FEATURES:
- Type-based object collection (charity, officer, grant, etc.)
- Ownership relationship management
- Direct database execution via save_to_database()
- Operation-based updates (XML file status, geocoding, etc.)
- Context merging for batch processing

INTEGRATION:
- Used by all processors for object accumulation
- Called by BaseConsumer.execute_contexts_batch()
- Works with DatabaseOperations.INSERT_BY_TYPE() for type-grouped inserts
"""

from typing import Dict, List, Any, Optional, Generator
from models import Charity, Officer, Grant, Contractor, PoliticalContribution, Address, Geocoding, ZipFile, XMLFile, AuthoritativeEin,IrsBmf
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from logging_utils import log_info, log_error, log_warning, log_debug
from datetime import datetime
import threading

PDC_DEBUG = False

class PendingDatabaseContext:
    """
    Context object that collects all database objects during XML parsing.

    This is the CORE data collection class in the PDC (PendingDatabaseContext) architecture.
    It accumulates database objects by type during processing, then executes them in the
    correct ownership order when save_to_database() is called.

    OBJECT ORGANIZATION:
    - Maintains type-based collections: charity, officer, grant, contractor, political_contribution, address
    - Handles ownership relationships automatically
    - Supports operation-based updates (XML status, geocoding, etc.)

    EXECUTION MODEL:
    - save_to_database(): Executes all collected objects via INSERT_BY_TYPE
    - Handles operations (XML updates, geocoding, deduplication)
    - Returns all generated IDs for relationship tracking

    THREADING: Safe for multi-threaded producers, single-threaded execution
    PERFORMANCE: Batches objects by type for efficient bulk inserts
    POOL INTEGRATION: Uses db_ops.acquire_write_conn() for tx management
    """
    _updated_counter = 0

    def __init__(self, xml_id: str = None, xml_content: bytes = None):
        """Initialize the context with empty collections"""
        self.xml_id = xml_id
        self.xml_content = xml_content
        self.objects: Dict[str, List[Any]] = {
            'charity': [],
            'irsbmf': [], # for IRS BMF records (not from XML, but collected during BMF processing)
            'officer': [],
            'grant': [],
            'contractor': [],
            'political_contribution': [],
            'address': [],
            'geocoding': [],  # For geocoding records
            'zipfile': [],  # For ZIP file records
            'authoritativeein': [],  # For AuthoritativeEin records
            'xmlfile': []   # For XML file records
        }
        self._updates: List[Dict[str, Any]] = []  # For future UPDATE operations
        self.operations: List[DatabaseOperation] = []  # For generic database operations
        self.error_message: Optional[str] = None  # Error message for failed processing
        self.estimated_updates: int = 0  # Estimated number of database updates this context will perform

    def addObjectToDatabase(self, obj: Any) -> None:
        """
        Add an object to the appropriate collection based on its type.

        Args:
            obj: The database model object to add (Charity, Officer, Grant, etc.)
        """
        obj_type = type(obj).__name__.lower()

        # Add to the appropriate list (no special handling for charity)
        if obj_type in self.objects:
            self.objects[obj_type].append(obj)
            # Increment estimated updates (rough estimate for size-based batching)
            self.estimated_updates += 1
            log_debug(f"Added {obj_type} object to PDC (total {len(self.objects[obj_type])})")
        else:
            raise ValueError(f"Unknown object type: {obj_type}")

    def updateObject(self, obj_type: str, obj_id: str, updates: Dict[str, Any]) -> None:
        """
        Record an UPDATE operation to be performed on an existing database object.

        Args:
            obj_type: The type of object to update (e.g., 'charity', 'officer')
            obj_id: The ID of the object to update
            updates: Dictionary of field updates (column -> value)
        """
        self._updates.append({
            'type': obj_type,
            'id': obj_id,
            'updates': updates
        })

    def addOperationToDatabase(self, operation: DatabaseOperation) -> None:
        """
        Add a generic database operation to be executed.

        Args:
            operation: The DatabaseOperation to add
        """
        self.operations.append(operation)
        # Increment estimated updates (rough estimate for size-based batching)
        self.estimated_updates += 1
        log_debug(f"Added operation {operation.operation_type} to PDC (total {len(self.operations)})")

    def getObjectsByType(self, obj_type: str) -> List[Any]:
        """
        Get all objects of a specific type.

        Args:
            obj_type: The object type to retrieve ('charity', 'officer', etc.)

        Returns:
            List of objects of the specified type
        """
        return self.objects.get(obj_type, [])

    def getCharity(self) -> Optional[Charity]:
        """
        Get the first charity object if available.

        Returns:
            The first Charity object, or None if no charities exist
        """
        charities = self.getObjectsByType('charity')
        return charities[0] if charities else None

    def getAllObjects(self) -> Dict[str, List[Any]]:
        """
        Get all objects organized by type.

        Returns:
            Dictionary mapping object types to lists of objects
        """
        return self.objects.copy()

    def getUpdates(self) -> List[Dict[str, Any]]:
        """
        Get all recorded UPDATE operations.

        Returns:
            List of update operations
        """
        return self._updates.copy()
    
    def getUpdatesCount(self) -> int:
        return len(self._updates)
    
    def getOperationsCount(self)-> int:
        return len(self.operations)

    def isEmpty(self) -> bool:
        """Check if this context contains any objects"""
        return all(not objs for objs in self.objects.values())

    def getObjectCounts(self) -> Dict[str, int]:
        """
        Get counts of objects by type.

        Returns:
            Dictionary mapping object types to counts
        """
        return {obj_type: len(objects) for obj_type, objects in self.objects.items()}

    def count_geocoding_status_updates(self) -> int:
        """Rows with a terminal/intermediate geocoding_status write (excludes canonical-only touch-ups)."""
        n = 0
        for operation in self.operations:
            if operation.operation_type != DatabaseOperationType.GENERIC_UPDATE:
                continue
            data = operation.data or {}
            if data.get('table') != 'Geocoding':
                continue
            for upd in data.get('updates') or []:
                if 'geocoding_status' in upd:
                    n += 1
        return n

    def count_completed_work_items(self) -> int:
        """Pipeline rows whose admission slot should be released when this PDC is consumed."""
        rows = self.count_geocoding_status_updates()
        if rows > 0:
            return rows
        progress = 0
        for operation in self.operations:
            if operation.operation_type != DatabaseOperationType.PROGRESS_UPDATE:
                continue
            progress += int((operation.data or {}).get('count') or 0)
        return progress or 1

    def getTotalObjectCount(self) -> int:
        """
        Get total count of all objects in this context.

        Returns:
            Total number of objects across all types
        """
        return sum(len(objects) for objects in self.objects.values())

    def save_to_database(self, db_ops: DatabaseOperations, checkpoint: bool = False) -> List[str]:
        """
        Execute all collected objects and operations directly with periodic flushing.
        This is the PRIMARY execution method for PDC. It handles both:
        1. Objects collected via addObjectToDatabase (using INSERT_BY_TYPE for each type)
        2. Operations collected via addOperationToDatabase (XML updates, geocoding, etc.)
        
        EXECUTION ORDER:
        - Objects inserted first (by type, respecting ownership)
        - Operations executed second (updates, geocoding, etc.)
        
        Args:
            db_ops: DatabaseOperations instance for executing operations
        
        Returns:
            List of generated IDs from all inserted objects (for relationship tracking)
        
        THREADING: Must be called from single consumer thread (DuckDB writer constraint)
        PERFORMANCE: Batches by type for efficient bulk inserts
        """
        if PDC_DEBUG: print(f"###DEBUG### PDC_SAVE: Starting save_to_database with {len(self.operations)} operations")
        if not self.operations and all(not objs for objs in self.objects.values()):
           if PDC_DEBUG: print("###DEBUG### PDC_SAVE: No operations or objects to save, returning early")
           return []

        ids: List[str] = []
        with db_ops.acquire_write_conn() as conn:

            # Commit after each large bulk/WHERE op so Geocoding status is durable
            # even if a later Addresses/owner UPDATE OOMs (was rolling back everything).
            FLUSH_EVERY_N_ROWS = 100
            # Always checkpoint after Geocoding bulk so max-files loops keep progress.
            COMMIT_AFTER_TABLES = {"geocoding", "addresses"}

            try:
                # Start explicit transaction
                log_debug("###DEBUG### PDC_SAVE: Beginning transaction")
                if PDC_DEBUG: print("###DEBUG### PDC_SAVE: Beginning transaction")
                try:
                    conn.execute("BEGIN TRANSACTION")
                except Exception as begin_e:
                    # Already in a transaction (re-entrant writer) — continue
                    if "within a transaction" not in str(begin_e).lower():
                        raise

                # Insert any real objects first (normal for XML parsing, skipped in address dedup)
                for obj_type in ['zipfile', 'xmlfile', 'charity', 'officer', 'grant',
                                    'contractor', 'political_contribution', 'address', 'geocoding','irsbmf']:
                    objects = self.objects.get(obj_type, [])
                    if objects:   # <-- only call if there are actual objects
                        if PDC_DEBUG: print(f"###DEBUG### PDC_SAVE: Inserting {len(objects)} {obj_type} objects")
                        new_ids = db_ops.INSERT_BY_TYPE(objects, obj_type.capitalize(), commit_batches=False)
                        PendingDatabaseContext._updated_counter += len(new_ids or [])
                        if new_ids:
                            ids.extend(new_ids)

                # Execute operations with periodic flushing
                print(f"###DEBUG### PDC_SAVE: Executing {len(self.operations)} operations")
                for i, operation in enumerate(self.operations):
                    if PDC_DEBUG: print(f"###DEBUG### PDC_SAVE: Executing operation {i+1}/{len(self.operations)}: type={operation.operation_type}, data_keys={list(operation.data.keys()) if operation.data else 'None'}")
                    try:
                        self._execute_operation(db_ops, operation, conn=conn)
                    except Exception as op_e:
                        err = str(op_e).lower()
                        # If we already committed Geocoding, log and continue so partial
                        # progress survives; OOM hard-exits inside bulk_update.
                        log_error(
                            f"PDC_SAVE: op {i+1}/{len(self.operations)} failed "
                            f"({operation.operation_type}): {op_e}"
                        )
                        if "out of memory" in err or "failed to offload" in err or "failed to pin" in err:
                            from database_operations import _oom_hard_exit
                            _oom_hard_exit("pdc_save_op", op_e)
                        # Non-OOM: rollback current tx segment and continue next ops
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        try:
                            conn.execute("BEGIN TRANSACTION")
                        except Exception:
                            pass
                        continue

                    if operation.operation_type == DatabaseOperationType.GENERIC_UPDATE:
                        table = (operation.data.get('table') or operation.data.get('table_name') or "").lower()
                        if 'updates' in operation.data:
                            rows_this_op = len(operation.data['updates'])
                            if PDC_DEBUG: print(f"###DEBUG### PDC_SAVE: GENERIC_UPDATE with {rows_this_op} updates to table {operation.data.get('table')}")
                        elif 'where_clause' in operation.data:
                            param_sets = operation.data.get('param_sets')
                            if param_sets:
                                rows_this_op = len(param_sets)
                                if PDC_DEBUG: print(f"###DEBUG### PDC_SAVE: WHERE_UPDATE batched with {len(param_sets)} param sets")
                            else:
                                rows_this_op = 1
                                if PDC_DEBUG: print(f"###DEBUG### PDC_SAVE: WHERE_UPDATE single")
                        else:
                            rows_this_op = 0
                            if PDC_DEBUG: print("###DEBUG### PDC_SAVE: GENERIC_UPDATE unknown format")

                        PendingDatabaseContext._updated_counter += rows_this_op

                        force_flush = (
                            table in COMMIT_AFTER_TABLES and rows_this_op >= 25
                        ) or PendingDatabaseContext._updated_counter >= FLUSH_EVERY_N_ROWS
                        if force_flush:
                            if PDC_DEBUG: print(f"###DEBUG### PDC_SAVE: Triggering intermediate commit after {PendingDatabaseContext._updated_counter} updates table={table}")
                            PendingDatabaseContext._updated_counter = self._intermediate_commit_and_checkpoint(
                                conn, PendingDatabaseContext._updated_counter, db_ops
                            )
                            try:
                                conn.execute("BEGIN TRANSACTION")
                            except Exception as begin_e:
                                if "within a transaction" not in str(begin_e).lower():
                                    log_warning(f"BEGIN after intermediate flush: {begin_e}")
                            PendingDatabaseContext._updated_counter = 0

                # Final commit
                if PDC_DEBUG: print("###DEBUG### PDC_SAVE: Executing final commit")
                conn.commit()
                if PDC_DEBUG: print("###DEBUG### PDC_SAVE: Final commit completed successfully")
                log_info("Final commit completed – address deduplication batch saved")

            except Exception as e:
                print(f"###DEBUG### PDC_SAVE: ERROR during save: {e}")
                try:
                    conn.rollback()
                except:
                    pass
                log_error(f"Failed to save context to database: {e}", exc_info=True)
                raise

            if checkpoint:
                self._force_checkpoint(conn, label="final")

            if PDC_DEBUG: print(f"###DEBUG### PDC_SAVE: Completed save_to_database, returned {len(ids)} IDs")
        return ids

    def _execute_operation(
        self,
        db_ops: DatabaseOperations,
        operation: DatabaseOperation,
        conn=None,
    ) -> None:
        """
        Execute a single database operation.

        Args:
            db_ops: DatabaseOperations instance
            operation: The operation to execute
            conn: Optional open write connection (keep nested bulk_update in outer tx)
        """

        op_type = operation.operation_type
        data = operation.data

        if op_type == DatabaseOperationType.XML_FILE_UPDATE:
            self._execute_xml_file_update(db_ops, operation)
        elif op_type == DatabaseOperationType.UPDATE_XML_EIN:
            self._execute_update_xml_ein(db_ops, operation)
        elif op_type == DatabaseOperationType.OPTIMIZE_DATABASE:
            db_ops.optimize_database()
        elif op_type == DatabaseOperationType.GENERIC_UPDATE:
            self._execute_generic_update(db_ops, operation, conn=conn)
        elif op_type == DatabaseOperationType.PROGRESS_UPDATE:
            from logging_utils import update_progress
            update_progress(n=operation.data.get("count", 0))
        elif op_type == DatabaseOperationType.INSERT_GEOCODING:
            self._execute_insert_geocoding(db_ops, operation)
        elif op_type == DatabaseOperationType.UPDATE_GEOCODING:
            self._execute_update_geocoding(db_ops, operation)
        elif op_type == DatabaseOperationType.UPDATE_ADDRESS_GEOCODING:
            self._execute_update_address_geocoding(db_ops, operation)
        elif op_type == DatabaseOperationType.AUTHORITATIVE_EIN_UPDATE:
            name = data['name']
            colocator = data['colocator']
            ein = data['ein']
            db_ops.update_authoritative_ein(name, colocator, ein)
        # Add other operation types as needed

    def _execute_xml_file_update(self, db_ops: DatabaseOperations, operation: DatabaseOperation) -> None:
        """Execute XML file update operation"""
        metadata = operation.data
        xml_id = operation.xml_id
    
        from constants import CURRENT_PROCESSING_VERSION
        db_ops.execute_query("""
            UPDATE XmlFiles SET
                processed = ?,
                processing_version = ?,
                file_size = ?,
                ein = ?,
                tax_year = ?,
                form_type = ?,
                org_type = ?,
                error_message = ?,
                processed_at = ?
            WHERE xml_id = ?
        """, (
            metadata["processed"],
            CURRENT_PROCESSING_VERSION,
            metadata["file_size"],
            metadata["ein"],
            metadata["tax_year"],
            metadata["form_type"],
            metadata.get("org_type"),
            metadata["error_message"],
            datetime.now().isoformat() if metadata["processed"] else None,
            xml_id
        ))

    def _execute_update_xml_ein(self, db_ops: DatabaseOperations, operation: DatabaseOperation) -> None:
        """Execute UPDATE_XML_EIN operation"""
        xml_id = operation.xml_id
        data = operation.data
        ein = data.get("ein") if data else None
        if ein:
            db_ops.execute_query("UPDATE XmlFiles SET ein = ? WHERE xml_id = ?", (ein, xml_id))


    def _execute_generic_update(
        self,
        db_ops: DatabaseOperations,
        operation: DatabaseOperation,
        conn=None,
    ) -> int:
        """Execute generic update operation"""
        data = operation.data
        updated_count = 0

        # Check if this is a WHERE clause update (optimization for address deduplication)
        where_clause = data.get('where_clause')
        if where_clause:
            # WHERE clause update - delegate to database_operations
            db_ops._execute_generic_update_operation(operation, conn)
            # For WHERE updates, we can't easily get the row count, so return 0
            # The actual update happened in database_operations
            return 0
        else:
            # Traditional bulk update by ID
            table_name = data.get("table") or data.get("table_name")
            update_data = data.get("updates") or data.get("update_data", [])
            id_column = data.get("key_field") or data.get("id_column", "id")

            if table_name and update_data:
                # Stay inside outer save_to_database transaction when conn is provided.
                # commit=False + commit_batches for large lists keeps DuckDB memory down.
                n = len(update_data) if isinstance(update_data, list) else 1
                use_batch_commit = n >= 100 and conn is None
                batch_size = 50 if n >= 100 else 100
                if isinstance(update_data, list):
                    updated_count = db_ops.bulk_update(
                        table_name,
                        update_data,
                        id_column=id_column,
                        batch_size=batch_size,
                        commit=conn is None,
                        commit_batches=use_batch_commit,
                        conn=conn,
                    )
                else:
                    # Single update - wrap in list for bulk_update
                    key_value = data.get("key_value")
                    if key_value is not None:
                        update_record = {**update_data, id_column: key_value}
                        updated_count = db_ops.bulk_update(
                            table_name,
                            [update_record],
                            id_column=id_column,
                            commit=conn is None,
                            conn=conn,
                        )
                    else:
                        # Fallback for old format
                        updated_count = db_ops.bulk_update(
                            table_name,
                            [update_data],
                            id_column=id_column,
                            commit=conn is None,
                            conn=conn,
                        )

        return updated_count

    def _execute_insert_geocoding(self, db_ops: DatabaseOperations, operation: DatabaseOperation) -> None:
        """Execute geocoding insert operation"""
        data = operation.data
        normalized_address = data.get("normalized_address")
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        status = data.get("status", "pending")

        if normalized_address is not None:
            geocoding_id = db_ops.insert_geocoding_record(normalized_address, latitude, longitude, status, commit=False)

    def _execute_update_geocoding(self, db_ops: DatabaseOperations, operation: DatabaseOperation) -> None:
        """Execute geocoding update operation"""
        data = operation.data
        table_name = data.get("table")
        update_data = data.get("updates", {})
        key_field = data.get("key_field", "geocoding_id")
        key_value = data.get("key_value")

        if table_name and update_data and key_value is not None:
            # Build SET clause from update_data (excluding the key field if present)
            set_parts = []
            params = []
            for field, value in update_data.items():
                if field != key_field:  # Don't include key field in SET clause
                    set_parts.append(f"{field} = ?")
                    params.append(value)

            if set_parts:
                set_clause = ", ".join(set_parts)
                sql = f"UPDATE {table_name} SET {set_clause} WHERE {key_field} = ?"
                params.append(key_value)
                db_ops.execute_query(sql, tuple(params))

    def _execute_update_address_geocoding(self, db_ops: DatabaseOperations, operation: DatabaseOperation) -> None:
        """Execute address geocoding update operation"""
        # The operation.data should now contain a Geocoding object
        geocoding = operation.data
        if geocoding and hasattr(geocoding, 'canonical_address') and hasattr(geocoding, 'geocoding_id'):
            # Create colocator from geocoding results
            colocator = None
            if geocoding.latitude is not None and geocoding.longitude is not None:
                colocator = f"LL:{geocoding.latitude}:{geocoding.longitude}"

            if geocoding.canonical_address:
                try:
                    db_ops.update_address_geocoding_by_canonical(geocoding.canonical_address, geocoding.geocoding_id, colocator)
                except Exception as e:
                    # Log the error but don't fail the entire transaction
                    log_error(f"Failed to update addresses for canonical_address {geocoding.canonical_address}: {e}")
                    # Continue with the transaction - geocoding record update will still succeed
    def _log_geocoding_status_counts(self, conn, label: str = "checkpoint") -> None:
        """Emit status histogram for monitor after checkpoint — single grep-friendly line."""
        try:
            rows = conn.execute(
                "SELECT geocoding_status, COUNT(*) AS n "
                "FROM Geocoding GROUP BY geocoding_status ORDER BY n DESC"
            ).fetchall()
            parts = [f"{status}={count:,}" for status, count in rows]
            msg = f"GEOCODING_STATUS_COUNTS ({label}) " + " ".join(parts)
            log_info(msg)
            print(msg, flush=True)
        except Exception as e:
            log_warning(f"GEOCODING_STATUS_COUNTS failed ({label}): {e}")

    def _force_checkpoint(self, conn, label: str = "checkpoint") -> None:
        try:
            conn.execute("PRAGMA force_checkpoint")
            log_info(f"FORCE CHECKPOINT completed ({label})")
            self._log_geocoding_status_counts(conn, label=label)
        except Exception as e:
            log_warning(f"FORCE CHECKPOINT failed ({label}): {e}")

    def _intermediate_commit_and_checkpoint(self, conn, updated_so_far: int, db_ops: DatabaseOperations) -> int:
        """Commit + FORCE CHECKPOINT — frees WAL/memory during long write drains."""
        try:
            log_debug("Performing intermediate commit and force checkpoint...")
            conn.commit()
            self._force_checkpoint(conn, label=f"intermediate ~{updated_so_far:,} rows")
            log_info(f"INTERMEDIATE COMMIT + FORCE CHECKPOINT after ~{updated_so_far:,} updates")
            return 0

        except Exception as e:
            current_thread_id = threading.get_ident()
            err = str(e).lower()
            log_warning(
                f"Intermediate commit/checkpoint failed on thread {current_thread_id}: {e}"
            )
            # OOM during COMMIT is fatal for this process — hard-exit so the
            # outer max-files loop restarts clean (sys.exit left zombies before).
            if (
                "out of memory" in err
                or "failed to offload" in err
                or "failed to pin" in err
                or "could not allocate" in err
            ):
                from database_operations import _oom_hard_exit
                _oom_hard_exit("intermediate_commit", e)
            try:
                conn.execute("BEGIN TRANSACTION")
            except Exception:
                pass
        return 0

    @classmethod
    def merge(cls, contexts: List['PendingDatabaseContext']) -> 'PendingDatabaseContext':
        """
        Merge multiple PendingDatabaseContext objects into a single context.

        This method combines all objects from multiple contexts into one,
        following the architecture's requirement for efficient batch processing.
        Used by parallel producers to consolidate results before consumer execution.

        Args:
            contexts: List of PendingDatabaseContext objects to merge

        Returns:
            Single PendingDatabaseContext containing all objects from input contexts

        THREADING: Safe for merging results from parallel producer threads
        PERFORMANCE: Enables batch processing of multiple XML files at once
        """
        if PDC_DEBUG: print(f"###DEBUG### PDC_MERGE: Merging {len(contexts)} contexts")
        if not contexts:
            if PDC_DEBUG: print("###DEBUG### PDC_MERGE: No contexts to merge, returning empty")
            return cls()
        # Always consolidate ops (even a single fat PDC from pending_api fail
        # can hold 100+ 1-row GENERIC_UPDATEs that OOM DuckDB).

        # Use the first context as the base
        merged = cls(xml_id=contexts[0].xml_id, xml_content=contexts[0].xml_content)

        # Collect all error messages from contexts that have them
        error_messages = [ctx.error_message for ctx in contexts if ctx.error_message]
        if error_messages:
            merged.error_message = '\n'.join(error_messages)
        else:
            merged.error_message = None

        # Merge all objects from all contexts
        for context in contexts:
            # Merge all objects
            for obj_type, objects in context.objects.items():
                merged.objects[obj_type].extend(objects)

            # Merge updates
            merged._updates.extend(context._updates)

        # Consolidate operations - group GENERIC_UPDATE ops for real bulk writes.
        # Without this, census/geocode merge keeps 1-row updates per match and DuckDB
        # OOMs after ~50–100 individual UPDATEs against a large Geocoding table.
        from database_operations import DatabaseOperationType
        where_update_groups = {}  # (table, set_clause, where_clause) -> list of params
        # (table, id_column, col_tuple) -> list of update dicts (same columns)
        bulk_update_groups: Dict[tuple, List[Dict[str, Any]]] = {}

        for context in contexts:
            merged.estimated_updates += context.estimated_updates

            for operation in context.operations:
                if operation.operation_type == DatabaseOperationType.GENERIC_UPDATE:
                    data = operation.data
                    where_clause = data.get('where_clause')
                    if where_clause:
                        table = data.get('table')
                        set_clause = data.get('set_clause')
                        key = (table, set_clause, where_clause)
                        if data.get('param_sets'):
                            where_update_groups.setdefault(key, []).extend(data['param_sets'])
                        elif 'params' in data:
                            where_update_groups.setdefault(key, []).append(data.get('params') or [])
                    elif 'updates' in data or 'update_data' in data:
                        table = data.get('table') or data.get('table_name')
                        id_column = data.get('key_field') or data.get('id_column', 'id')
                        update_data = data.get('updates') or data.get('update_data') or []
                        if isinstance(update_data, dict):
                            update_data = [update_data]
                        for row in update_data:
                            if not isinstance(row, dict):
                                continue
                            # Column signature must match for one executemany SQL
                            col_key = tuple(sorted(row.keys()))
                            gkey = (table, id_column, col_key)
                            bulk_update_groups.setdefault(gkey, []).append(row)
                    else:
                        merged.operations.append(operation)
                else:
                    merged.operations.append(operation)

        # Geocoding bulk first (status/coords), then owner bulk, then Addresses WHERE.
        # Status rows must land even if colocator propagation is heavy.
        def _bulk_sort_key(item):
            (table, _idc, _cols), _rows = item
            t = (table or "").lower()
            if t == "geocoding":
                return (0, t)
            if t == "addresses":
                return (2, t)
            return (1, t)

        for (table, id_column, col_key), rows in sorted(
            bulk_update_groups.items(), key=_bulk_sort_key
        ):
            ordered_cols = list(col_key)
            normalized = [{c: r[c] for c in ordered_cols} for r in rows]
            merged.operations.append(DatabaseOperation(
                operation_type=DatabaseOperationType.GENERIC_UPDATE,
                data={
                    'table': table,
                    'updates': normalized,
                    'id_column': id_column,
                },
            ))

        for (table, set_clause, where_clause), param_sets in where_update_groups.items():
            if len(param_sets) == 1:
                merged.operations.append(DatabaseOperation(
                    operation_type=DatabaseOperationType.GENERIC_UPDATE,
                    data={
                        'table': table,
                        'set_clause': set_clause,
                        'where_clause': where_clause,
                        'params': param_sets[0],
                    },
                ))
            else:
                merged.operations.append(DatabaseOperation(
                    operation_type=DatabaseOperationType.GENERIC_UPDATE,
                    data={
                        'table': table,
                        'set_clause': set_clause,
                        'where_clause': where_clause,
                        'param_sets': param_sets,
                    },
                ))

        # Collapse PROGRESS_UPDATE noise into one op
        progress_total = 0
        kept: List[DatabaseOperation] = []
        for op in merged.operations:
            if op.operation_type == DatabaseOperationType.PROGRESS_UPDATE:
                progress_total += int(op.data.get("count", 0) or 0)
            else:
                kept.append(op)
        if progress_total:
            kept.append(DatabaseOperation(
                operation_type=DatabaseOperationType.PROGRESS_UPDATE,
                data={"count": progress_total},
            ))
        merged.operations = kept

        if PDC_DEBUG or len(contexts) > 10:
            n_bulk = sum(
                len(op.data.get('updates') or [])
                for op in merged.operations
                if op.operation_type == DatabaseOperationType.GENERIC_UPDATE
                and 'updates' in (op.data or {})
            )
            log_info(
                f"PDC_MERGE: {len(contexts)} ctxs → {len(merged.operations)} ops "
                f"(~{n_bulk} bulk-update rows, estimated_updates={merged.estimated_updates})"
            )
        return merged

    def clear(self) -> None:
        """Clear all objects from this context"""
        self.objects = {key: [] for key in self.objects.keys()}
        self._updates = []
        self.operations = []
        self.xml_id = None
        self.xml_content = None
        self.error_message = None
        self.estimated_updates = 0