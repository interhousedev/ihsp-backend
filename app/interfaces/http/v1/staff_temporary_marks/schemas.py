"""Schemas of the staff temporary gradebook routes."""

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field


class TemporaryMarkBody(BaseModel):
    """A temporary mark on the EMIS scale (2 to 5) with an optional comment."""

    value: int = Field(ge=2, le=5)
    comment: str | None = Field(default=None, max_length=500)


class TemporaryMarkResponse(BaseModel):
    """A temporary mark with student, group, subject and lesson names."""

    id: UUID
    lesson_id: UUID
    lesson_date: dt.date
    lesson_period: int
    student_id: UUID
    student_name: str
    group_id: UUID | None
    group_name: str
    subject_id: UUID
    subject_name: str
    teacher_id: UUID | None
    teacher_name: str
    value: int
    comment: str | None
    author_id: UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class TemporaryMarkListResponse(BaseModel):
    """Temporary marks, oldest lesson first."""

    items: list[TemporaryMarkResponse]
