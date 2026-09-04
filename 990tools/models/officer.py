#!/usr/bin/env python3
"""
models/officer.py - Officer data model

This module contains the Officer dataclass and related business logic.
Officers represent key personnel of charities with compensation information.
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import BaseModel


@dataclass
class Officer(BaseModel):
    """Represents a charity officer with compensation information"""

    officer_id: Optional[str] = field(default=None, init=False)
    charity_id: Optional[str] = None
    master_id: Optional[str] = None
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    compensation: float = 0.0
    tax_year: int = 0
    photo_url: Optional[str] = None
    colocator: Optional[str] = None
    created_at: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Get display name of the officer (computed from first/last if full_name not set)"""
        if self.full_name:
            return self.full_name
        return f"{self.first_name or ''} {self.last_name or ''}".strip()

    def is_highly_compensated(self) -> bool:
        """Check if officer compensation exceeds $200,000"""
        return self.compensation > 200000.0

    def build_address(self, address_line1: Optional[str] = None, address_line2: Optional[str] = None,
                      city: Optional[str] = None, state: Optional[str] = None, zip_code: Optional[str] = None,
                      zip4: Optional[str] = None) -> 'Address':
        """Build an Address dataclass record owned by this officer"""
        from .address import Address
        # Ensure we have an ID for the owner_id
        if self.officer_id is None:
            self.officer_id = self.generate_id()
        address = Address(
            ein="",  # Officers don't have EINs
            name=self.display_name or "Unknown Officer",
            address_line1=address_line1 or "",
            address_line2=address_line2 or "",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            zip4=zip4 or "",
            address_type="officer",
            owner_id=self.officer_id
        )
        address.prep_for_insert()
        if address.colocator: self.colocator = address.colocator

        return address

    def prep_for_insert(self):
        """Prepare the record for database insertion"""
        super().prep_for_insert()
        pass

    @classmethod
    def create_for_charity(cls, charity, first_name: str, last_name: str, full_name: str, compensation: float, tax_year: int) -> 'Officer':
        """Factory method to create an Officer for a specific charity"""
        return cls(
            charity_id=charity.id,
            first_name=first_name or "",
            last_name=last_name or "",
            full_name=full_name or "",
            compensation=compensation,
            tax_year=tax_year
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'officer_id': self.officer_id,
            'charity_id': self.charity_id or "",
            'master_id': self.master_id or "",
            'first_name': self.first_name or "",
            'last_name': self.last_name or "",
            'full_name': self.full_name or "",
            'compensation': self.compensation,
            'tax_year': self.tax_year,
            'photo_url': self.photo_url or "",
            'colocator': self.colocator or "",
            'created_at': self.created_at or ""
        }