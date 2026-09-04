#!/usr/bin/env python3
"""
models/dedup_work_item.py - Deduplication work item for address processing

This dataclass represents a unit of work for address deduplication, standardizing
the queue items as real objects per project conventions. Includes validation to
ensure data integrity before queuing.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class DedupWorkItem:
    """
    Represents a deduplication work item for a group of addresses sharing
    the same canonical_address.

    Ensures the master address is included in child_address_ids for consistency
    in batch updates, allowing the database operation to handle self-referencing
    idempotently.
    """
    canonical_address: str
    master_address_id: str
    child_address_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate the work item post-initialization."""
        if not self.canonical_address or not self.canonical_address.strip():
            raise ValueError("canonical_address cannot be empty")
        if not self.master_address_id:
            raise ValueError("master_address_id is required")
        if len(self.child_address_ids) < 1:
            raise ValueError("At least one child address ID is required")
        # Ensure master is included in child_ids for batch consistency
        if self.master_address_id not in self.child_address_ids:
            self.child_address_ids.append(self.master_address_id)