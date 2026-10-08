"""Request and response models of the EMIS sync monitor."""

import datetime as dt
from uuid import UUID

from pydantic import BaseModel


class SyncRunItemResponse(BaseModel):
    """One EMIS sync run."""

    id: UUID
    started_at: dt.datetime
    finished_at: dt.datetime | None
    status: str
    stats: dict[str, int]


class SyncRunPageResponse(BaseModel):
    """A page of sync runs, newest first."""

    items: list[SyncRunItemResponse]
    next_cursor: str | None = None


class RunSyncBody(BaseModel):
    """Start a sync for one student, or for everybody when ``user_id`` is absent."""

    user_id: UUID | None = None
