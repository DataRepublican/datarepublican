from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from uuid import uuid4  # Simulate UUIDv7; replace with real uuid7 lib
from .base_model import BaseModel
from .address import Address

@dataclass
class FECCommittee(BaseModel):
    fec_cmte_id: str
    name: str
    treasurer_name: Optional[str] = None
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
        self.report_year = self.report_year or datetime.now().year
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": str(uuid4()),  # UUIDv7
            "fec_cmte_id": self.fec_cmte_id,
            "name": self.name,
            "treasurer_name": self.treasurer_name,
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
            normalized=True  # Assuming Address.py has normalization logic
        )]