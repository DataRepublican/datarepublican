#!/usr/bin/env python3
"""FEC committee model."""

from dataclasses import dataclass
from typing import Optional
from .base import BaseModel
from .address import Address


@dataclass
class FecCommittee(BaseModel):
    id: Optional[str] = None
    fec_cmte_id: str = ""
    name: str = ""
    treasurer_name: Optional[str] = None
    report_year: int = 0
    colocator_id: Optional[str] = None
    colocation_score: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    charity_ein: Optional[str] = None

    def prep_for_insert(self) -> None:
        super().prep_for_insert()

    def build_address(
        self,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        zip4: Optional[str] = None,
    ) -> Address:
        if self.id is None:
            self.id = self.generate_id()
        address = Address(
            ein="",
            name=self.name or "Unknown",
            address_line1=address_line1 or "",
            address_line2=address_line2 or "",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            zip4=zip4 or "",
            address_type="fec_committee",
            owner_id=self.id,
        )
        address.prep_for_insert()
        return address

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fec_cmte_id": self.fec_cmte_id,
            "name": self.name,
            "treasurer_name": self.treasurer_name,
            "report_year": self.report_year,
            "colocator_id": self.colocator_id,
            "colocation_score": self.colocation_score,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "charity_ein": self.charity_ein,
        }