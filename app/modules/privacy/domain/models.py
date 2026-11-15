"""Erasure requests and data exports."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

EXPORT_VALID_DAYS = 7
EXPORT_INTERVAL_HOURS = 24


class ErasureStatus(StrEnum):
    """Where an erasure request is."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"  # the 30-day window runs
    REJECTED = "rejected"
    COMPLETED = "completed"
    CANCELLED = "cancelled"  # the user restored the account in the window


class ExportStatus(StrEnum):
    """Where a data export is."""

    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class ErasureRequest:
    """A user's request to erase their account and personal data."""

    id: UUID
    user_id: UUID
    status: ErasureStatus
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    reject_reason: str | None = None
    closes_on: date | None = None
    completed_at: datetime | None = None


@dataclass(slots=True)
class ExportJob:
    """A data export of one user."""

    id: UUID
    user_id: UUID
    status: ExportStatus
    created_at: datetime
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    storage_key: str | None = None
    byte_size: int | None = None
    error: str | None = None

    def is_downloadable(self, now: datetime) -> bool:
        """Ready and not expired."""
        return (
            self.status is ExportStatus.READY
            and self.storage_key is not None
            and self.expires_at is not None
            and self.expires_at > now
        )
