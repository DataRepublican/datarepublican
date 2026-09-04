#!/usr/bin/env python3
"""FEC committee-to-committee transaction model."""

from dataclasses import dataclass
from typing import Optional
from .base import BaseModel
from .address import Address


@dataclass
class FecCommitteeTransaction(BaseModel):
    id: Optional[str] = None
    fec_sub_id: str = ""
    fec_cmte_id: str = ""
    other_cmte_id: str = ""
    transaction_amount: float = 0.0
    transaction_date: Optional[str] = None
    transaction_type: str = ""
    report_year: int = 0
    colocator_id: Optional[str] = None
    colocation_score: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def prep_for_insert(self) -> None:
        super().prep_for_insert()

    def build_address(
        self,
        name: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        zip4: Optional[str] = None,
    ) -> Address:
        if self.id is None:
            self.id = self.generate_id()
        address = Address(
            ein="",
            name=name or "Unknown",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            zip4=zip4 or "",
            address_type="fec_committee_transaction",
            owner_id=self.id,
        )
        address.prep_for_insert()
        return address

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fec_sub_id": self.fec_sub_id,
            "fec_cmte_id": self.fec_cmte_id,
            "other_cmte_id": self.other_cmte_id,
            "transaction_amount": self.transaction_amount,
            "transaction_date": self.transaction_date,
            "transaction_type": self.transaction_type,
            "report_year": self.report_year,
            "colocator_id": self.colocator_id,
            "colocation_score": self.colocation_score,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }