#!/usr/bin/env python3
"""Medicare / NPPES provider model."""

from dataclasses import dataclass
from typing import Optional
from .base import BaseModel
from .address import Address


@dataclass
class MedicareProvider(BaseModel):
    id: Optional[str] = None
    npi: str = ""
    entity_type_code: Optional[str] = None
    ein: Optional[str] = None
    organization_name: Optional[str] = None
    provider_last_name: Optional[str] = None
    provider_first_name: Optional[str] = None
    provider_middle_name: Optional[str] = None
    provider_credential: Optional[str] = None
    enumeration_date: Optional[str] = None
    last_update_date: Optional[str] = None
    is_sole_proprietor: Optional[str] = None
    created_at: Optional[str] = None

    def prep_for_insert(self) -> None:
        super().prep_for_insert()

    @property
    def display_name(self) -> str:
        if self.organization_name and str(self.organization_name).strip():
            return str(self.organization_name).strip()
        parts = [self.provider_first_name or "", self.provider_last_name or ""]
        name = " ".join(p for p in parts if p).strip()
        return name or "Unknown"

    @staticmethod
    def display_name_sql(alias: str) -> str:
        """SQL expression matching display_name (for NPI joins in bulk ingest)."""
        return f"""COALESCE(
            NULLIF(TRIM({alias}.organization_name), ''),
            NULLIF(TRIM(COALESCE({alias}.provider_first_name, '') || ' ' || COALESCE({alias}.provider_last_name, '')), '')
        )"""

    def build_address(
        self,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        zip4: Optional[str] = None,
        address_type: str = "nppes_practice",
    ) -> Address:
        if self.id is None:
            self.id = self.generate_id()
        address = Address(
            ein=self.ein or "",
            name=self.display_name,
            address_line1=address_line1 or "",
            address_line2=address_line2 or "",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            zip4=zip4 or "",
            address_type=address_type,
            owner_id=self.id,
        )
        address.prep_for_insert()
        return address

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "npi": self.npi,
            "entity_type_code": self.entity_type_code,
            "ein": self.ein,
            "organization_name": self.organization_name,
            "provider_last_name": self.provider_last_name,
            "provider_first_name": self.provider_first_name,
            "provider_middle_name": self.provider_middle_name,
            "provider_credential": self.provider_credential,
            "enumeration_date": self.enumeration_date,
            "last_update_date": self.last_update_date,
            "is_sole_proprietor": self.is_sole_proprietor,
            "created_at": self.created_at,
        }