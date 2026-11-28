"""Schemas of the non-lesson block routes."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import ApiModel

from pydantic import BaseModel, Field

DayBlockKindValue = Literal["lunch", "second_lunch", "break", "assembly", "other"]
DayBlockScopeValue = Literal["all", "course", "groups"]


class DayBlockBody(BaseModel):
    """Body of POST /v1/admin/day-blocks and PUT /v1/admin/day-blocks/{id}.

    `weekdays` are ISO numbers, Monday 1 … Friday 5. `course` is required for the
    scope `course`; `group_ids` must not be empty for the scope `groups`.
    """

    name: str = Field(min_length=1, max_length=120)
    kind: DayBlockKindValue
    starts_at: dt.time
    ends_at: dt.time
    weekdays: list[int] = Field(min_length=1, max_length=5)
    scope: DayBlockScopeValue = "all"
    course: int | None = Field(default=None, ge=1, le=9)
    group_ids: list[UUID] = Field(default_factory=list, max_length=500)


class DayBlockResponse(ApiModel):
    """A non-lesson block (lunch, second lunch, break, assembly)."""

    id: UUID
    name: str
    kind: DayBlockKindValue
    starts_at: dt.time
    ends_at: dt.time
    weekdays: list[int]
    scope: DayBlockScopeValue
    course: int | None
    group_ids: list[UUID]


class DayBlockOccurrenceResponse(ApiModel):
    """A non-lesson block on one date of the student's timetable."""

    id: UUID
    date: dt.date
    name: str
    kind: DayBlockKindValue
    starts_at: dt.time
    ends_at: dt.time
