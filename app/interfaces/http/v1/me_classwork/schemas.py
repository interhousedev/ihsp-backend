"""Response and request models of the classwork endpoints (§ API contract)."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PersonRefResponse(BaseModel):
    """``PersonRef``."""

    id: UUID
    first_name: str
    last_name: str


class SubjectRefResponse(BaseModel):
    """``SubjectRef``."""

    id: UUID
    name: str
    short_name: str


class RoomRefLiteResponse(BaseModel):
    """``RoomRefLite``."""

    id: UUID
    slug: str | None
    name: str | None


class AudienceItemResponse(BaseModel):
    """``AudienceItem``."""

    group_id: UUID
    group_name: str
    subgroup: Literal[1, 2] | None


class LessonItemResponse(BaseModel):
    """``LessonItem``."""

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
    has_homework: bool
    attendance_submitted: bool


class ResourceItemResponse(BaseModel):
    """``ResourceItem``; ``file`` and ``created_at`` are null (links contract gap)."""

    link_id: UUID
    lesson_id: UUID
    role: Literal["material", "attachment", "homework"]
    kind: Literal["url", "file"]
    short_url: str
    title: str
    author: PersonRefResponse
    hidden: bool
    file: dict[str, Any] | None
    created_at: dt.datetime | None


class HomeworkItemResponse(BaseModel):
    """``HomeworkItem``; ``days_overdue`` is 0 unless the open item is past due."""

    lesson_id: UUID
    subject: SubjectRefResponse
    teacher: PersonRefResponse | None
    text: str
    due_date: dt.date | None
    given_on: dt.date
    days_overdue: int
    updated: bool
    done_at: dt.datetime | None
    note: str | None


class MarkItemResponse(BaseModel):
    """``MarkItem``."""

    subject: SubjectRefResponse
    semester: int
    type: Literal["lesson", "midterm", "final"]
    value: int
    date: dt.date
    lesson_id: UUID | None


class NowOrNextResponse(LessonItemResponse):
    """A lesson with the time left and the number of materials."""

    minutes_left: int | None
    materials_count: int


class DayLessonResponse(LessonItemResponse):
    """A lesson of today with its state."""

    state: Literal["done", "now", "next", "later", "cancelled"]


class SemesterCardResponse(BaseModel):
    """The "This semester" card."""

    semester: int | None
    gpa: float | None
    gpa_change: float | None
    absences: int


class StudentTodayResponse(BaseModel):
    """``StudentToday``."""

    now_or_next: NowOrNextResponse | None
    lessons: list[DayLessonResponse]
    next_study_day: dt.date | None
    due: list[HomeworkItemResponse]
    new_marks: list[MarkItemResponse]
    semester: SemesterCardResponse
    synced_at: dt.datetime | None


class StudentLessonResponse(BaseModel):
    """``StudentLesson``."""

    lesson: LessonItemResponse
    materials: list[ResourceItemResponse]
    attachments: list[ResourceItemResponse]
    homework: HomeworkItemResponse | None
    my_mark: list[MarkItemResponse]
    my_attendance: Literal["present", "absent", "excused", "not_taken"]
    can_attach: bool


class SubjectAttendanceResponse(BaseModel):
    """A row of the student's attendance summary."""

    subject: SubjectRefResponse
    absences: int
    excused: int
    lessons: int
    rate: float | None


class AbsenceDayResponse(BaseModel):
    """A day with absences."""

    date: dt.date
    absences: int


class MissedLessonResponse(BaseModel):
    """A missed lesson."""

    lesson: LessonItemResponse
    excused: bool


class StudentAttendanceResponse(BaseModel):
    """``StudentAttendance`` (the JSON keys are ``from`` and ``to``)."""

    model_config = ConfigDict(populate_by_name=True)

    from_: dt.date = Field(alias="from")
    to: dt.date
    summary: list[SubjectAttendanceResponse]
    days: list[AbsenceDayResponse]
    missed: list[MissedLessonResponse]
    not_taken: int


class HomeworkDoneBody(BaseModel):
    """Body of ``PUT /v1/me/homework/{lesson_id}/done``."""

    done: bool


class HomeworkNoteBody(BaseModel):
    """Body of ``PUT /v1/me/homework/{lesson_id}/note``."""

    note: str | None
