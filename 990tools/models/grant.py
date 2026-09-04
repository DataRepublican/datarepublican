#!/usr/bin/env python3
"""
models/grant.py - Grant data model

This module contains the Grant dataclass and related business logic.
Grants represent charitable contributions made by filers to other organizations.
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid7 import generate_uuid_v7
from .base import BaseModel
from .address import Address
import fuzzy
import re

CLEAN_AND = re.compile(r'\s+and\s+', re.IGNORECASE)
STRIP_SUFFIX = re.compile(r'\s+(inc|corp|llc|foundation|association|society|institute|trust|nonprofit|center|program|fdn|federation|national|international)$', re.IGNORECASE)


@dataclass
class Grant(BaseModel):
    """Represents a charitable grant from one organization to another"""

    grant_id: Optional[str] = field(default=None, init=False)
    charity_id: Optional[str] = None
    filer_ein: str = ""
    filer_name: str = ""
    grantee_sndx: Optional[str] = None  # Precomputed double metaphone for fuzzy matching
    grantee_name: str = ""
    recipient_ein: Optional[str] = None
    grant_amt: float = 0.0
    tax_year: int = 0
    colocator: Optional[str] = None
    filer_colocator: Optional[str] = None
    created_at: Optional[str] = None
    grantee_sndx: Optional[str] = None  # Precomputed soundex for fuzzy matching

    def is_large_grant(self) -> bool:
        """Check if grant amount exceeds $100,000"""
        return self.grant_amt > 100000

    def is_foreign_grant(self) -> bool:
        """Check if grant is to a foreign recipient"""
        return bool(self.recipient_ein and (self.recipient_ein.startswith('99') or self.recipient_ein == '999'))

    def build_address(self, address_line1: Optional[str] = None, address_line2: Optional[str] = None,
                     city: Optional[str] = None, state: Optional[str] = None, zip_code: Optional[str] = None,
                     zip4: Optional[str] = None) -> Address:
        """Build an Address dataclass record owned by this grant"""
        address = Address(
            ein=self.recipient_ein or "",
            name=self.grantee_name or "Unknown Grantee",
            address_line1=address_line1 or "",
            address_line2=address_line2 or "",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            zip4=zip4 or "",
            address_type="grant",
            owner_id=self.id  # This ensures owner_id is always set since self.id creates the primary key if needed
        )
        address.prep_for_insert()
        if address.colocator: self.colocator = address.colocator

        return address

    def prep_for_insert(self):
        """Prepare the record for database insertion"""
        super().prep_for_insert()
        cleaned_name = STRIP_SUFFIX.sub('', CLEAN_AND.sub(' & ', self.grantee_name.lower()))
        primary, secondary = fuzzy.DMetaphone()(cleaned_name)
        self.grantee_sndx = f"{primary}|{secondary}" if primary and secondary else primary or secondary or ''
        pass

    @property
    def id(self) -> str:
        """Get the primary key, creating it if necessary"""
        if self.grant_id is None:
            self.grant_id = generate_uuid_v7()
        return self.grant_id

    @classmethod
    def create_for_charity(cls, charity, grantee_name: str, recipient_ein: Optional[str], grant_amt: float, tax_year: int) -> 'Grant':
        """Factory method to create a Grant for a specific charity"""
        return cls(
            filer_ein=charity.ein or "",
            filer_name=charity.filer_name or "",
            grantee_name=grantee_name or "",
            recipient_ein=recipient_ein or "",
            grant_amt=grant_amt,
            tax_year=tax_year,
            charity_id=charity.id
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'grant_id': self.grant_id,
            'charity_id': self.charity_id,
            'filer_ein': self.filer_ein or "",
            'filer_name': self.filer_name or "",
            'grantee_name': self.grantee_name or "",
            'grantee_sndx': self.grantee_sndx,
            'recipient_ein': self.recipient_ein or "",
            'grant_amt': self.grant_amt,
            'tax_year': self.tax_year,
            'colocator': self.colocator or "",
            'created_at': self.created_at or ""
        },
           