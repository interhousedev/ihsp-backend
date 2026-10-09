"""Response schemas shared by the schedule routes (PersonRef, SubjectRef, ...)."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.shared.lesson_kind import LessonKind, TopicSource

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base of schedule schemas: built from dataclasses and dicts."""

    model_config = ConfigDict(from_attributes=True)


class PersonRefResponse(ApiModel):
    """PersonRef."""

    id: UUID
    first_name: str
    last_name: str


class SubjectRefResponse(ApiModel):
    """SubjectRef in the caller's locale."""

    id: UUID
    name: str
    short_name: str | None


class RoomRefLiteResponse(ApiModel):
    """RoomRefLite."""

    id: UUID
    slug: str
    name: str


class AudienceItemResponse(ApiModel):
    """AudienceItem."""

    group_id: UUID
    group_name: str
    subgroup: Literal[1, 2] | None


class AudienceBody(BaseModel):
    """One audience entry of an input: a group and an optional subgroup."""

    group_id: UUID
    subgroup: Literal[1, 2] | None = None


class LessonItemResponse(ApiModel):
    """LessonItem."""

    id: UUID
    date: dt.date
    period: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject: SubjectRefResponse
    teacher: PersonRefResponse | None
    room: RoomRefLiteResponse | None
    audience: list[AudienceItemResponse]
    status: Literal["scheduled", "cancelled"]
    is_overridden: bool
    changes: dict[str, list[Any]] | None
    topic: str | None
    kind: LessonKind = "other"
    # "emis": the topic came from EMIS (a hint); "manual": a person wrote it.
    topic_source: TopicSource | None = None
    has_homework: bool
    attendance_submitted: bool
