#!/usr/bin/env python3
"""FMCSA DOT motor carrier model."""

from dataclasses import dataclass
from typing import Optional

from .address import Address
from .base import BaseModel


@dataclass
class DotCarrier(BaseModel):
    id: Optional[str] = None
    dot_number: str = ""
    legal_name: Optional[str] = None
    dba_name: Optional[str] = None
    status_code: Optional[str] = None
    carrier_operation: Optional[str] = None
    business_org_desc: Optional[str] = None
    phone: Optional[str] = None
    email_address: Optional[str] = None
    power_units: Optional[int] = None
    truck_units: Optional[int] = None
    fleetsize: Optional[str] = None
    docket1: Optional[str] = None
    docket1prefix: Optional[str] = None
    mcs150_date: Optional[str] = None
    add_date: Optional[str] = None
    created_at: Optional[str] = None

    @property
    def display_name(self) -> str:
        if self.legal_name and str(self.legal_name).strip():
            return str(self.legal_name).strip()
        if self.dba_name and str(self.dba_name).strip():
            return str(self.dba_name).strip()
        return f"DOT {self.dot_number}"

    def build_address(
        self,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        address_type: str = "dot_carrier_phy",
    ) -> Address:
        if self.id is None:
            self.id = self.generate_id()
        address = Address(
            ein="",
            name=self.display_name,
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