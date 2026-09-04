#!/usr/bin/env python3
"""
models/zip_file.py - ZIP file data model

This module contains the ZipFile dataclass and related business logic.
ZIP files represent compressed archives containing IRS 990 XML filings.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime
from .base import BaseModel


@dataclass
class ZipFile(BaseModel):
    """Represents a ZIP file containing IRS 990 XML filings"""

    zip_id: Optional[str] = None
    filename: str = ""
    file_path: str = ""
    tax_year: int = 0
    file_size: Optional[int] = None
    checksum: Optional[str] = None
    download_date: Optional[datetime] = None
    processed_date: Optional[datetime] = None
    status: str = "downloaded"
    xml_files: List['XMLFile'] = field(default_factory=list)
    created_at: Optional[str] = None

    def is_processed_successfully(self) -> bool:
        """Check if ZIP file was processed without errors"""
        return self.status == 'processed'

    def mark_processed(self, xml_count: int = 0, error_message: Optional[str] = None):
        """Mark ZIP file as fully registered (XmlFiles rows written / already present)."""
        self.status = 'processed'
        self.processed_date = datetime.now()

    # get_db_field_names is now inherited from BaseModel and uses dataclass fields

    def create_xml_file(self, filename: str, internal_path: str, file_size: Optional[int] = None) -> 'XMLFile':
        """Factory method to create XMLFile objects with correct zip_id"""
        from .xml_file import XMLFile
        return XMLFile(
            zip_id=self.zip_id,
            filename=filename,
            internal_path=internal_path,
            file_size=file_size
        )

    @classmethod
    def create_from_path(cls, zip_path: str, tax_year: int, file_size: Optional[int] = None) -> 'ZipFile':
        """Factory method to create a ZipFile from a file path"""
        from pathlib import Path
        path = Path(zip_path)
        return cls(
            filename=path.name,
            file_path=str(path),
            tax_year=tax_year,
            file_size=file_size or path.stat().st_size if path.exists() else None,
            status='downloaded'
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'zip_id': self.zip_id,
            'filename': self.filename,
            'file_path': self.file_path,
            'tax_year': self.tax_year,
            'file_size': self.file_size,
            'checksum': self.checksum,
            'download_date': self.download_date.isoformat() if self.download_date else None,
            'processed_date': self.processed_date.isoformat() if self.processed_date else None,
            'status': self.status,
            'created_at': self.created_at
        }