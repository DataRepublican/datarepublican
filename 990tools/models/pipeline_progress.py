#!/usr/bin/env python3
"""
models/pipeline_progress.py - Pipeline Progress data model

This module contains the PipelineProgress dataclass and related business logic.
PipelineProgress tracks processing pipeline status.
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid7 import generate_uuid_v7


@dataclass
class PipelineProgress:
    """Represents pipeline processing progress"""

    progress_id: Optional[str] = field(default=None, init=False)
    step_name: str = ""
    start_year: int = 0
    end_year: int = 0
    status: str = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    records_processed: int = 0
    error_message: Optional[str] = None

    def is_pending(self) -> bool:
        """Check if step is pending"""
        return self.status == "pending"

    def is_running(self) -> bool:
        """Check if step is running"""
        return self.status == "running"

    def is_completed(self) -> bool:
        """Check if step is completed"""
        return self.status == "completed"

    def is_failed(self) -> bool:
        """Check if step failed"""
        return self.status == "failed"

    def mark_started(self):
        """Mark the step as started"""
        self.status = "running"
        # Note: In a real implementation, set started_at to current timestamp

    def mark_completed(self, records: int = 0):
        """Mark the step as completed"""
        self.status = "completed"
        self.records_processed = records
        # Note: In a real implementation, set completed_at to current timestamp

    def mark_failed(self, error: str = ""):
        """Mark the step as failed"""
        self.status = "failed"
        self.error_message = error

    def prep_for_insert(self):
        """Prepare the record for database insertion"""
        super().prep_for_insert()
        pass

    @property
    def id(self) -> str:
        """Get the primary key, creating it if necessary"""
        if self.progress_id is None:
            self.progress_id = generate_uuid_v7()
        return self.progress_id

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'progress_id': self.progress_id,
            'step_name': self.step_name,
            'start_year': self.start_year,
            'end_year': self.end_year,
            'status': self.status,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'records_processed': self.records_processed,
            'error_message': self.error_message
        }