"""Schemas of the term routes."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import ApiModel
from app.modules.academic.domain.schedule.term import Bell, MovedDay

from pydantic import BaseModel, Field


class TermInputBody(BaseModel):
    """TermInput."""

    academic_year: str = Field(min_length=1, max_length=16)
    half: Literal[1, 2]
    starts_on: dt.date
    ends_on: dt.date
    bells: list[Bell] = Field(default_factory=list)
    non_study_days: list[dt.date] = Field(default_factory=list)
    moved_days: list[MovedDay] = Field(default_factory=list)


class TermPatchBody(BaseModel):
    """A partial TermInput: omitted fields stay as they are."""

    academic_year: str | None = Field(default=None, min_length=1, max_length=16)
    half: Literal[1, 2] | None = None
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None
    bells: list[Bell] | None = None
    non_study_days: list[dt.date] | None = None
    moved_days: list[MovedDay] | None = None


class TermResponse(ApiModel):
    """Term."""

    id: UUID
    academic_year: str
    half: int
    starts_on: dt.date
    ends_on: dt.date
    bells: list[Bell]
    non_study_days: list[dt.date]
    moved_days: list[MovedDay]
    is_current: bool
