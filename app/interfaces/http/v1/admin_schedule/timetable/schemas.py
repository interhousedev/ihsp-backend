"""Schemas of the timetable routes."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import (
    ApiModel,
    AudienceBody,
    AudienceItemResponse,
    PersonRefResponse,
    RoomRefLiteResponse,
    SubjectRefResponse,
)

from pydantic import BaseModel, Field

WeekParityName = Literal["every", "odd", "even"]


class TimetableEntryInputBody(BaseModel):
    """TimetableEntryInput."""

    term_id: UUID
    weekday: int = Field(ge=1, le=6)
    period: int = Field(ge=1, le=20)
    week_parity: WeekParityName = "every"
    subject_id: UUID
    teacher_id: UUID | None = None
    room_name: str | None = Field(default=None, max_length=255)
    audience: list[AudienceBody] = Field(min_length=1, max_length=20)
    valid_from: dt.date
    valid_to: dt.date | None = None


class TimetableEntryPatchBody(BaseModel):
    """A partial TimetableEntryInput; send null to clear teacher, room or valid_to."""

    term_id: UUID | None = None
    weekday: int | None = Field(default=None, ge=1, le=6)
    period: int | None = Field(default=None, ge=1, le=20)
    week_parity: WeekParityName | None = None
    subject_id: UUID | None = None
    teacher_id: UUID | None = None
    room_name: str | None = Field(default=None, max_length=255)
    audience: list[AudienceBody] | None = Field(
        default=None, min_length=1, max_length=20
    )
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


class CopyBody(BaseModel):
    """Body of POST /v1/admin/timetable/copy."""

    from_term_id: UUID
    to_term_id: UUID


class CopyResponse(BaseModel):
    """Result of copying a timetable."""

    created: int


class TimetableEntryResponse(ApiModel):
    """TimetableEntry."""

    id: UUID
    term_id: UUID
    weekday: int
    period: int
    week_parity: WeekParityName
    subject: SubjectRefResponse
    teacher: PersonRefResponse | None
    room: RoomRefLiteResponse | None
    audience: list[AudienceItemResponse]
    valid_from: dt.date
    valid_to: dt.date | None
    # "emis": imported from EMIS and kept equal to it; editing it makes it "manual".
    source: Literal["manual", "emis"] = "manual"


class ConflictResponse(ApiModel):
    """Conflict; ``week_parity`` says in which weeks the other entry runs."""

    kind: Literal["teacher", "room", "audience"]
    with_entry_id: UUID | None
    with_lesson_id: UUID | None
    description: str
    week_parity: WeekParityName | None = None


class CheckResponse(BaseModel):
    """Result of POST /v1/admin/timetable/check."""

    conflicts: list[ConflictResponse]
