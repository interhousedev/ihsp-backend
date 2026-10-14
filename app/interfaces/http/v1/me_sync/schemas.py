"""Schemas of the student's full EMIS sync."""

import datetime as dt
from typing import Literal

from app.modules.academic.application.schedule.student_sync_state import SyncState

from pydantic import BaseModel


class SyncStatusResponse(BaseModel):
    """The last sync: queued, running, done or failed, and when."""

    status: Literal["queued", "running", "done", "failed"]
    requested_at: dt.datetime
    finished_at: dt.datetime | None
    detail: str | None

    @classmethod
    def of(cls, state: SyncState) -> "SyncStatusResponse":
        """Build from the use case result."""
        return cls(
            status=state.status,
            requested_at=state.requested_at,
            finished_at=state.finished_at,
            detail=state.detail,
        )
