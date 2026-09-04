from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from uuid import uuid4
from .base_model import BaseModel
from .address import Address

@dataclass
class FECOperatingExpenditure(BaseModel):
    fec_sub_id: str
    fec_cmte_id: str
    payee_name: str
    expenditure_amount: float
    expenditure_date: datetime
    purpose: str
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
        self.report_year = self.report_year or self.expenditure_date.year
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": str(uuid4()),
            "fec_sub_id": self.fec_sub_id,
            "fec_cmte_id": self.fec_cmte_id,
            "payee_name": self.payee_name,
            "expenditure_amount": self.expenditure_amount,
            "expenditure_date": self.expenditure_date.isoformat(),
            "purpose": self.purpose,
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