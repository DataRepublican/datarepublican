#!/usr/bin/env python3
"""
models/xml_file.py - XML file data model

This module contains the XMLFile dataclass and related business logic.
XML files represent individual IRS 990 filings extracted from ZIP archives.
"""

from dataclasses import dataclass
from typing import Optional, List, Tuple
from datetime import datetime
from .base import BaseModel


@dataclass
class XMLFile(BaseModel):
    """Represents an individual IRS 990 XML filing"""

    xml_id: Optional[str] = None
    zip_id: Optional[str] = None
    filename: str = ""
    internal_path: str = ""
    file_size: Optional[int] = None
    ein: Optional[str] = None
    tax_year: Optional[int] = None
    form_type: Optional[str] = None
    processed: bool = False
    processing_version: int = 0
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    org_type: Optional[str] = None
    processed_at: Optional[str] = None

    def is_processed_successfully(self) -> bool:
        """Check if XML file was processed without errors"""
        return self.processed and not self.error_message

    def mark_processed(self, error_message: Optional[str] = None):
        """Mark XML file as processed"""
        self.processed = True
        self.processed_at = datetime.now().isoformat()
        self.error_message = error_message

    def prep_for_insert(self):
        """Prepare the record for database insertion"""
        # Ensure zip_id is a string, not None
        if self.zip_id is None:
            self.zip_id = ""
        elif not isinstance(self.zip_id, str):
            self.zip_id = str(self.zip_id)
        # Ensure xml_id is set
        if not self.xml_id:
            self.xml_id = self.generate_id()
        # Ensure processing_version is not None
        if self.processing_version is None:
            self.processing_version = 0
        pass

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'xml_id': self.xml_id,
            'zip_id': self.zip_id,
            'filename': self.filename,
            'internal_path': self.internal_path,
            'file_size': self.file_size,
            'ein': self.ein,
            'tax_year': self.tax_year,
            'form_type': self.form_type,
            'org_type': self.org_type,
            'processed': self.processed,
            'processing_version': self.processing_version,
            'error_message': self.error_message,
            'created_at': self.created_at,
            'processed_at': self.processed_at
        }

    @classmethod
    def get_xml_files_to_process(cls, db_ops) -> List[Tuple]:
        """Get list of XML files to process from database"""
        query = """
            SELECT xf.xml_id, zf.file_path, xf.filename, xf.internal_path, xf.file_size
            FROM XmlFiles xf
            JOIN ZipFiles zf ON xf.zip_id = zf.zip_id
            WHERE xf.processed = FALSE
            ORDER BY xf.xml_id
        """
        result = db_ops.execute_query(query)
        return result.fetchall()

    @classmethod
    def get_xml_files_to_process(cls, db_ops, limit: Optional[int] = None) -> List[Tuple]:
        """Get list of XML files to process from database"""
        query = """
            SELECT xf.xml_id, zf.file_path, xf.filename, xf.internal_path, xf.file_size
            FROM XmlFiles xf
            JOIN ZipFiles zf ON xf.zip_id = zf.zip_id
            WHERE xf.processed = FALSE
            ORDER BY xf.xml_id
        """
        if limit is not None:
            query += f" LIMIT {limit}"
        result = db_ops.execute_query(query)
        return result.fetchall()