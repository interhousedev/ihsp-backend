"""Schemas of the lesson routes."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import (
    AudienceBody,
    LessonItemResponse,
)
from app.shared.pagination import Page

from pydantic import BaseModel, Field


class ExtraLessonInputBody(BaseModel):
    """ExtraLessonInput."""

    date: dt.date
    period: int = Field(ge=1, le=20)
    subject_id: UUID
    teacher_id: UUID | None = None
    room_name: str | None = Field(default=None, max_length=255)
    audience: list[AudienceBody] = Field(min_length=1, max_length=20)
    topic: str | None = Field(default=None, max_length=500)


class LessonPatchBody(BaseModel):
    """Body of PATCH /v1/admin/lessons/{id}; null clears teacher, room or topic."""

    status: Literal["scheduled", "cancelled"] | None = None
    teacher_id: UUID | None = None
    subject_id: UUID | None = None
    room_name: str | None = Field(default=None, max_length=255)
    date: dt.date | None = None
    period: int | None = Field(default=None, ge=1, le=20)
    topic: str | None = Field(default=None, max_length=500)


LessonPageResponse = Page[LessonItemResponse]
