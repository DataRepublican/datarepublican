#!/usr/bin/env python3
"""FEC individual contribution model."""

from dataclasses import dataclass
from typing import Optional
from .base import BaseModel
from .address import Address


@dataclass
class FecIndividualContribution(BaseModel):
    id: Optional[str] = None
    fec_sub_id: str = ""
    fec_cmte_id: str = ""
    contributor_name: str = ""
    contribution_amount: float = 0.0
    contribution_date: Optional[str] = None
    occupation: Optional[str] = None
    employer: Optional[str] = None
    report_year: int = 0
    colocator_id: Optional[str] = None
    colocation_score: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def prep_for_insert(self) -> None:
        super().prep_for_insert()

    def build_address(
        self,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        zip4: Optional[str] = None,
    ) -> Address:
        if self.id is None:
            self.id = self.generate_id()
        address = Address(
            ein="",
            name=self.contributor_name or "Unknown",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            zip4=zip4 or "",
            address_type="fec_contributor",
            owner_id=self.id,
        )
        address.prep_for_insert()
        return address

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fec_sub_id": self.fec_sub_id,
            "fec_cmte_id": self.fec_cmte_id,
            "contributor_name": self.contributor_name,
            "contribution_amount": self.contribution_amount,
            "contribution_date": self.contribution_date,
            "occupation": self.occupation,
            "employer": self.employer,
            "report_year": self.report_year,
            "colocator_id": self.colocator_id,
            "colocation_score": self.colocation_score,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }