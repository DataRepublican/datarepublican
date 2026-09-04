#!/usr/bin/env python3
"""
models/political_contribution.py - Political contribution data model

This module contains the PoliticalContribution dataclass and related business logic.
Political contributions represent payments made to political organizations.
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import BaseModel
from .address import Address


@dataclass
class PoliticalContribution(BaseModel):
    """Represents a political contribution made by a charity"""

    political_id: Optional[int] = field(default=None, init=False)
    filer_ein: str = ""
    recipient: str = ""
    amount: float = 0.0
    recipient_ein: Optional[str] = None
    tax_year: int = 0
    colocator: Optional[str] = None
    created_at: Optional[str] = None

    def is_large_contribution(self) -> bool:
        """Check if contribution exceeds $10,000"""
        return self.amount > 10000.0

    def build_address(self, address_line1: Optional[str] = None, address_line2: Optional[str] = None,
                     city: Optional[str] = None, state: Optional[str] = None, zip_code: Optional[str] = None,
                     zip4: Optional[str] = None) -> Address:
        """Build an Address dataclass record owned by this political contribution"""
        address = Address(
            ein="",  # Political contributions may not have EINs
            name=self.recipient or "Unknown Recipient",
            address_line1=address_line1 or "",
            address_line2=address_line2 or "",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            zip4=zip4 or "",
            address_type="politicalcontribution",
            owner_id=self.id  # force creation
        )
        address.prep_for_insert()
        if address.colocator: self.colocator = address.colocator
        return address

    def prep_for_insert(self):
        """Prepare the record for database insertion"""
        super().prep_for_insert()
        pass

    @classmethod
    def create_for_charity(cls, charity, recipient: str, amount: float, tax_year: int) -> 'PoliticalContribution':
        """Factory method to create a PoliticalContribution for a specific charity"""
        return cls(
            filer_ein=charity.ein or "",
            charity_id=charity.id,
            recipient=recipient or "",
            amount=amount,
            tax_year=tax_year
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'political_id': self.political_id,
            'filer_ein': self.filer_ein or "",
            'recipient': self.recipient or "",
            'amount': self.amount,
            'charity_id': self.charity_id or "",
            'tax_year': self.tax_year,
            'colocator': self.colocator or "",
            'created_at': self.created_at or ""
        }