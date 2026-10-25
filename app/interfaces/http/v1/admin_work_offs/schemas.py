"""Response models of the administration work-off endpoints (WO-8)."""

import datetime as dt
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkOffStatsRowResponse(BaseModel):
    """Open and done counts of one subject, teacher, group or student."""

    key: UUID
    name: str
    open_count: int
    done_count: int


class WorkOffStatsResponse(BaseModel):
    """Work-off statistics (the JSON keys are ``from`` and ``to``)."""

    model_config = ConfigDict(populate_by_name=True)

    group_by: Literal["subject", "teacher", "group", "student"]
    from_: dt.date = Field(alias="from")
    to: dt.date
    total_open: int
    rows: list[WorkOffStatsRowResponse]


class AdminWorkOffItemResponse(BaseModel):
    """One work-off in the administration list."""

    id: UUID
    lesson_id: UUID
    date: dt.date
    period: int
    subject_name: str
    teacher_name: str | None
    group_name: str | None
    student_id: UUID
    student_name: str
    text: str
    status: Literal["assigned", "done"]
    due_date: dt.date | None
    done_at: dt.datetime | None
    created_at: dt.datetime


class AdminWorkOffListResponse(BaseModel):
    """A page of work-offs and the total count."""

    total: int
    items: list[AdminWorkOffItemResponse]
