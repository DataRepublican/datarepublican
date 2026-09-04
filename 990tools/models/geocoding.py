#!/usr/bin/env python3
"""
models/geocoding.py - Geocoding data model

This module contains the Geocoding dataclass and related business logic.
Geocoding represents cached geocoding results for addresses.
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid7 import generate_uuid_v7
from models.base import BaseModel


@dataclass
class Geocoding(BaseModel):
    """Represents cached geocoding results for an address"""

    geocoding_id: Optional[str] = field(default=None, init=False)
    canonical_address: str = ""
    normalized_address: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geocoding_status: str = "pending"
    last_attempt: Optional[str] = None
    attempt_count: int = 0
    matched_address: Optional[str] = None

    def __post_init__(self):
        """Generate geocoding_id if not set during instantiation"""
        if self.geocoding_id is None:
            self.geocoding_id = generate_uuid_v7()

    def is_successful(self) -> bool:
        """Check if geocoding was successful"""
        return self.geocoding_status == "success"

    def is_failed(self) -> bool:
        """Check if geocoding failed"""
        return self.geocoding_status == "failed"

    def is_pending(self) -> bool:
        """Check if geocoding is pending"""
        return self.geocoding_status == "pending"

    def increment_attempts(self):
        """Increment the attempt count"""
        self.attempt_count += 1

    def prep_for_insert(self):
        """Prepare the record for database insertion"""
        super().prep_for_insert()
        # geocoding_id is now generated in __post_init__, but ensure it's set
        if self.geocoding_id is None:
            self.geocoding_id = generate_uuid_v7()

    @property
    def id(self) -> str:
        """Get the primary key (geocoding_id is now generated in __post_init__)"""
        return self.geocoding_id

    @classmethod
    def get_db_field_names(cls):
        """Get database field names for this model"""
        return ['geocoding_id', 'canonical_address', 'normalized_address', 'latitude', 'longitude',
                'geocoding_status', 'last_attempt', 'attempt_count', 'matched_address']

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'geocoding_id': self.geocoding_id or "",
            'canonical_address': self.canonical_address or "",
            'normalized_address': self.normalized_address or "",
            'latitude': self.latitude,
            'longitude': self.longitude,
            'geocoding_status': self.geocoding_status or "pending",
            'last_attempt': self.last_attempt or "",
            'attempt_count': self.attempt_count,
            'matched_address': self.matched_address or ""
        }