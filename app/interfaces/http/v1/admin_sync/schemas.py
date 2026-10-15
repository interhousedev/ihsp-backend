"""Request and response models of the EMIS sync monitor."""

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field


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


class TermChoice(BaseModel):
    """An academic year and its half, e.g. 2026-2027 / 1."""

    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    half: int = Field(ge=1, le=2)


class ResyncMaterialsBody(BaseModel):
    """The terms whose EMIS materials are replaced."""

    terms: list[TermChoice] = Field(min_length=1, max_length=10)
