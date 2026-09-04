#!/usr/bin/env python3
"""
models/base.py - Base model class for all IRS 990 data models

This module provides an abstract base class for all model classes,
ensuring consistent ID generation and prep_for_insert functionality.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from typing import List, Optional, Dict
from functools import lru_cache
import duckdb


class BaseModel(ABC):
    """Abstract base class for all IRS 990 data models"""

    # Static cache for table columns to avoid repeated DESCRIBE calls
    _table_columns_cache: Dict[str, List[str]] = {}

    def prep_for_insert(self):
        """Prepare the record for database insertion - base implementation"""
        # Set ID if needed
        self.set_id_if_needed()
        pass

    @classmethod
    def _get_table_columns(cls, table_name: str, conn: Optional[duckdb.DuckDBPyConnection] = None) -> List[str]:
        """Get ordered column names from DESCRIBE (DB schema order)."""
        if table_name in cls._table_columns_cache:
            return cls._table_columns_cache[table_name]

        if conn is None:
            raise ValueError("Connection required for first-time column fetch")

        try:
            result = conn.execute(f"DESCRIBE {table_name}")
            columns = [row[0] for row in result.fetchall()]
            cls._table_columns_cache[table_name] = columns
            return columns
        except Exception as e:
            raise RuntimeError(f"Failed to fetch columns for {table_name}: {e}")

    @classmethod
    @lru_cache(maxsize=None)
    def get_db_field_names(cls) -> List[str]:
        """Get the field names that should be inserted into the database (cached)"""
        # Use dataclass fields to get field names
        field_names = []
        try:
            # Check if this is actually a dataclass before calling fields()
            if hasattr(cls, '__dataclass_fields__'):
                # Use the class itself as the argument to fields()
                for field in fields(cls):
                    field_names.append(field.name)
        except (TypeError, AttributeError):
            # Handle case where cls is not a dataclass or instantiation fails
            pass
        return field_names

    @classmethod
    def generate_id(cls) -> str:
        """Generate a UUID v7 for this model instance"""
        from uuid7 import generate_uuid_v7
        return str(generate_uuid_v7())

    def set_id_if_needed(self):
        """Set the ID field if it exists and is not set"""
        # For object tree relationships, we need to generate IDs client-side
        # Find the ID field (usually ends with '_id' or is just 'id')
        id_field = None
        for field_name in self.get_db_field_names():
            if field_name.endswith('_id') or field_name == 'id':
                id_field = field_name
                break

        if id_field and hasattr(self, id_field):
            current_value = getattr(self, id_field)
            if current_value is None or current_value == "":
                # Generate proper UUID v7 using our fixed implementation
                setattr(self, id_field, self.generate_id())