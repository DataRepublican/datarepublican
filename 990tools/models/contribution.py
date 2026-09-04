#!/usr/bin/env python3
"""
models/contribution.py - Contribution data model

This module contains the Contribution dataclass and related business logic.
Contributions represent political or other contributions made by charities.
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid7 import generate_uuid_v7


@dataclass
class Contribution:
    """Represents a contribution made by a charity"""

    contribution_id: Optional[str] = field(default=None, init=False)
    filer_ein: str = ""
    filer_name: str = ""
    recipient_ein: Optional[str] = None
    amount: float = 0.0
    tax_year: int = 0

    def is_large_contribution(self) -> bool:
        """Check if contribution amount exceeds $10,000"""
        return self.amount > 10000

    def prep_for_insert(self):
        """Prepare the record for database insertion"""
        pass

    @property
    def id(self) -> str:
        """Get the primary key, creating it if necessary"""
        if self.contribution_id is None:
            self.contribution_id = generate_uuid_v7()
        return self.contribution_id

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'contribution_id': self.contribution_id,
            'filer_ein': self.filer_ein,
            'filer_name': self.filer_name,
            'recipient_ein': self.recipient_ein,
            'amount': self.amount,
            'tax_year': self.tax_year
        }