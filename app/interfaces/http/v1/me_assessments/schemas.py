"""Schemas of assessments (midterm and final controls), student and staff."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import (
    AudienceBody,
    AudienceItemResponse,
    PersonRefResponse,
)
from app.modules.academic.domain.assessments.edit import (
    NOTE_MAX,
    ROOM_MAX,
    TITLE_MAX,
)

from pydantic import BaseModel, Field

AssessmentKind = Literal["midterm", "final", "other"]
AssessmentStatus = Literal["planned", "tentative", "cancelled"]
AssessmentSource = Literal["teacher", "admin", "emis", "head_student"]
ControlName = Literal["midterm_1", "midterm_2", "final"]


class AssessmentSubject(BaseModel):
    """A subject named in the caller's locale."""

    id: UUID
    name: str
    short_name: str


class ControlPeriodResponse(BaseModel):
    """The control week Administration set for the term."""

    start: dt.date
    end: dt.date


class AssessmentItem(BaseModel):
    """A control of a subject on a date.

    ``days_left`` counts from today to ``date`` (negative once it is past).
    ``has_date`` is false for a control week no teacher has given a subject date yet:
    then ``date`` is the week's start (today while the week runs) and ``period`` the
    week. ``status`` ``tentative`` means the date is not confirmed by a teacher or
    Administration.
    """

    id: UUID
    subject: AssessmentSubject
    kind: AssessmentKind
    title: str
    date: dt.date
    starts_at: dt.datetime | None
    lesson_id: UUID | None
    room: str | None
    status: AssessmentStatus
    source: AssessmentSource
    note: str | None
    days_left: int
    control: ControlName | None
    period: ControlPeriodResponse | None
    has_date: bool


class AssessmentListResponse(BaseModel):
    """Controls of the student, soonest first."""

    items: list[AssessmentItem]


class StaffAssessmentItem(AssessmentItem):
    """A control as staff see it: with its audience and author."""

    audience: list[AudienceItemResponse]
    created_by: PersonRefResponse | None
    created_at: dt.datetime | None
    updated_at: dt.datetime | None


class StaffAssessmentListResponse(BaseModel):
    """Controls for the staff portal or the admin list."""

    items: list[StaffAssessmentItem]


class ProposalBody(BaseModel):
    """A date a head student suggests for their group; it stays tentative."""

    subject_id: UUID
    kind: AssessmentKind
    date: dt.date
    title: str = Field(default="", max_length=TITLE_MAX)
    starts_at: dt.datetime | None = None
    room: str | None = Field(default=None, max_length=ROOM_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    control: ControlName | None = None


class AssessmentCreateBody(BaseModel):
    """A control a teacher or Administration plans."""

    subject_id: UUID
    audience: list[AudienceBody] = Field(min_length=1, max_length=20)
    kind: AssessmentKind
    date: dt.date
    title: str = Field(default="", max_length=TITLE_MAX)
    starts_at: dt.datetime | None = None
    room: str | None = Field(default=None, max_length=ROOM_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    lesson_id: UUID | None = None
    control: ControlName | None = None


class AssessmentPatchBody(BaseModel):
    """A partial edit: omitted fields stay, null clears the optional ones.

    ``status`` ``planned`` confirms a tentative control as it is and ``cancelled``
    dismisses it; changing any other field of a tentative control confirms it.
    """

    subject_id: UUID | None = None
    audience: list[AudienceBody] | None = Field(
        default=None, min_length=1, max_length=20
    )
    kind: AssessmentKind | None = None
    date: dt.date | None = None
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    starts_at: dt.datetime | None = None
    room: str | None = Field(default=None, max_length=ROOM_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    lesson_id: UUID | None = None
    control: ControlName | None = None
    status: Literal["planned", "cancelled"] | None = None
