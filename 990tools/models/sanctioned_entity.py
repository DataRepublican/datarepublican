#!/usr/bin/env python3
"""OFAC SDN sanctioned entity models."""

from dataclasses import dataclass
from typing import Optional

from .address import Address
from .base import BaseModel


@dataclass
class SanctionedEntity(BaseModel):
    id: Optional[str] = None
    ofac_uid: str = ""
    primary_name: Optional[str] = None
    entity_type: Optional[str] = None
    entity_subtype: Optional[str] = None
    list_type: Optional[str] = None
    list_date: Optional[str] = None
    remarks: Optional[str] = None
    source_issue_date: Optional[str] = None
    created_at: Optional[str] = None

    def build_address(
        self,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        address_type: str = "ofac_sanction",
    ) -> Address:
        if self.id is None:
            self.id = self.generate_id()
        address = Address(
            ein="",
            name=self.primary_name or "",
            address_line1=address_line1 or "",
            address_line2=address_line2 or "",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            address_type=address_type,
            owner_id=self.id,
        )
        address.prep_for_insert()
        return address


@dataclass
class SanctionedName(BaseModel):
    id: Optional[str] = None
    entity_id: str = ""
    name: str = ""
    alias_type: Optional[str] = None
    is_primary: bool = False
    low_quality: bool = False


@dataclass
class SanctionedIdentifier(BaseModel):
    id: Optional[str] = None
    entity_id: str = ""
    id_type: Optional[str] = None
    id_number: Optional[str] = None
    country: Optional[str] = None


@dataclass
class SanctionedProgram(BaseModel):
    id: Optional[str] = None
    entity_id: str = ""
    program_code: str = ""
    sanctions_type: Optional[str] = None