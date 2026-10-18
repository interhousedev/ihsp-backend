"""Schemas of the student's initial EMIS sync (sync with proof)."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.modules.academic.application.schedule.student_sync_jobs import (
    MAX_ATTEMPTS,
    StudentSyncJob,
)

from pydantic import BaseModel


class SyncStatusResponse(BaseModel):
    """The sync record: where it is, what it synced, and why it failed if it did."""

    user_id: UUID
    status: Literal["pending", "running", "succeeded", "failed"]
    attempts: int
    max_attempts: int = MAX_ATTEMPTS
    requested_at: dt.datetime
    next_attempt_at: dt.datetime | None
    finished_at: dt.datetime | None
    last_error: str | None
    subgroup: int | None
    marks_count: int | None

    @classmethod
    def of(cls, job: StudentSyncJob) -> "SyncStatusResponse":
        """Build from the job record."""
        return cls(
            user_id=job.user_id,
            status=job.status,
            attempts=job.attempts,
            requested_at=job.requested_at,
            next_attempt_at=job.next_attempt_at,
            finished_at=job.finished_at,
            last_error=job.last_error,
            subgroup=job.subgroup,
            marks_count=job.marks_count,
        )
