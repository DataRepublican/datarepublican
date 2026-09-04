from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from uuid import uuid4
from .base_model import BaseModel
from .address import Address

@dataclass
class FECCommitteeTransaction(BaseModel):
    fec_sub_id: str
    fec_cmte_id: str  # Recipient committee
    other_cmte_id: str  # Donor committee
    transaction_amount: float
    transaction_date: datetime
    transaction_type: str
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    report_year: int = 0
    colocator_id: Optional[str] = None
    colocation_score: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def prep_for_insert(self):
        self.report_year = self.report_year or self.transaction_date.year
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": str(uuid4()),
            "fec_sub_id": self.fec_sub_id,
            "fec_cmte_id": self.fec_cmte_id,
            "other_cmte_id": self.other_cmte_id,
            "transaction_amount": self.transaction_amount,
            "transaction_date": self.transaction_date.isoformat(),
            "transaction_type": self.transaction_type,
            "report_year": self.report_year,
            "colocator_id": self.colocator_id,
            "colocation_score": self.colocation_score,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def build_addresses(self) -> List[Address]:
        if not self.street:
            return []
        return [Address(
            street=self.street,
            city=self.city,
            state=self.state,
            zip_code=self.zip_code,
            normalized=True
        )]