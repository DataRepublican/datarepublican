#!/usr/bin/env python3
"""
models/backfill.py - Backfill data model for stub charities
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid7 import uuid7
from .base import BaseModel

@dataclass
class Backfill(BaseModel):
    """Represents a backfill stub for unmatched grant recipient EINs"""
    backfill_id: Optional[str] = field(default=None, init=False)
    grant_id: Optional[str] = None  # Reference to originating grant
    recipient_ein: str = ""
    name: str = ""
    colocator: Optional[str] = None
    source: str = "xml"
    zip_code: Optional[str] = None
    created_at: Optional[str] = None

    @property
    def id(self) -> str:
        if self.backfill_id is None:
            self.backfill_id = str(uuid7())
        return self.backfill_id

    def prep_for_insert(self) -> None:
        super().prep_for_insert()
        _ = self.id  # Ensure ID is generated