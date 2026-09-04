#!/usr/bin/env python3
"""
models/contractor.py - Contractor data model

This module contains the Contractor dataclass and related business logic.
Contractors represent independent contractors paid by charities.
"""

from dataclasses import dataclass
from typing import Optional
from .base import BaseModel
from .address import Address


@dataclass
class Contractor(BaseModel):
    """Represents an independent contractor paid by a charity"""

    contractor_id: Optional[str] = None
    charity_id: Optional[str] = None
    filer_ein: str = ""
    name: str = ""
    amount: float = 0.0
    ein: Optional[str] = None
    address: Optional[str] = None
    zip_code: Optional[str] = None
    po_box: Optional[str] = None
    tax_year: int = 0
    colocator: Optional[str] = None
    created_at: Optional[str] = None

    def is_highly_compensated(self) -> bool:
        """Check if contractor compensation exceeds $100,000"""
        return self.amount > 100000.0

    @property
    def id(self) -> str:
        """Primary key; generate UUID v7 on first access (same pattern as Grant/Officer)."""
        if self.contractor_id is None or self.contractor_id == "":
            self.contractor_id = self.generate_id()
        return str(self.contractor_id)

    def build_address(self, address_line1: Optional[str] = None, address_line2: Optional[str] = None,
                     city: Optional[str] = None, state: Optional[str] = None, zip_code: Optional[str] = None,
                     zip4: Optional[str] = None) -> Address:
        """Build an Address dataclass record owned by this contractor.

        Always sets owner_id via self.id so Addresses can join back to Contractors.
        (Older code used contractor_id only when already set — it was None at parse
        time, so production rows landed with owner_id NULL.)
        """
        address = Address(
            ein=self.ein or "",
            name=self.name,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            state=state,
            zip_code=zip_code,
            zip4=zip4,
            address_type="contractor",
            owner_id=self.id,
        )
        address.prep_for_insert()
        if address.colocator:
            self.colocator = address.colocator
        return address

    def prep_for_insert(self):
        """Prepare the record for database insertion"""
        super().prep_for_insert()
        # Ensure contractor_id exists even if build_address was never called
        _ = self.id
        pass

    @classmethod
    def create_for_charity(cls, charity, name: str, amount: float, ein: Optional[str], tax_year: int) -> 'Contractor':
        """Factory method to create a Contractor for a specific charity"""
        return cls(
            filer_ein=charity.ein,
            name=name,
            amount=amount,
            ein=ein,
            tax_year=tax_year
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'contractor_id': self.contractor_id,
            'charity_id': self.charity_id,
            'filer_ein': self.filer_ein,
            'name': self.name,
            'amount': self.amount,
            'ein': self.ein,
            'tax_year': self.tax_year,
            'colocator': self.colocator,
            'created_at': self.created_at
        }