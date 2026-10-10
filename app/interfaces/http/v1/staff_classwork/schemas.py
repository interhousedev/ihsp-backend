"""Response and request models of the staff classwork endpoints."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.me_classwork.schemas import (
    LessonItemResponse,
    PersonRefResponse,
    ResourceItemResponse,
    SubjectRefResponse,
)

from pydantic import BaseModel, ConfigDict, Field


class AttendanceLessonResponse(LessonItemResponse):
    """A lesson of today with attendance and homework badges."""

    attendance_missing: bool
    homework_missing: bool


class StaffTodayResponse(BaseModel):
    """``StaffToday``."""

    now_or_next: LessonItemResponse | None
    lessons: list[AttendanceLessonResponse]
    needs_attention: list[LessonItemResponse]


class RosterItemResponse(BaseModel):
    """``RosterItem`` plus ``counted``.

    ``counted`` is an addition to the contract: it tells whether a student
    without a subgroup is part of the saved audience (always true for others).
    """

    position: int
    user_id: UUID
    first_name: str
    last_name: str
    group_name: str
    subgroup_unset: bool
    absent: bool
    late: bool = False
    excused: bool
    excuse_comment: str | None
    counted: bool


class AttendanceSheetResponse(BaseModel):
    """``AttendanceSheet``."""

    lesson_id: UUID
    submitted: bool
    version: int
    editable: bool
    roster: list[RosterItemResponse]
    submitted_at: dt.datetime | None
    submitted_by: PersonRefResponse | None


class StaffHomeworkResponse(BaseModel):
    """Homework of a lesson as the teacher sees it."""

    text: str
    due_date: dt.date | None
    due_auto: bool


class StaffLessonResponse(BaseModel):
    """``StaffLesson``."""

    lesson: LessonItemResponse
    materials: list[ResourceItemResponse]
    attachments: list[ResourceItemResponse]
    homework: StaffHomeworkResponse | None
    attendance: AttendanceSheetResponse


class JournalLessonResponse(BaseModel):
    """A column of the journal."""

    id: UUID
    date: dt.date
    topic: str | None
    attendance_submitted: bool
    editable: bool
    version: int


class JournalCellResponse(BaseModel):
    """A cell of the journal."""

    lesson_id: UUID
    absent: bool
    late: bool = False
    excused: bool
    marks: list[int]


class JournalStudentResponse(BaseModel):
    """A row of the journal."""

    user_id: UUID
    first_name: str
    last_name: str
    cells: list[JournalCellResponse]
    absences: int
    lates: int = 0
    semester_mark: float | None


class JournalResponse(BaseModel):
    """``Journal`` (the audience key is extra context of the grid)."""

    subject: SubjectRefResponse
    audience_key: str
    lessons: list[JournalLessonResponse]
    students: list[JournalStudentResponse]


class JournalOptionResponse(BaseModel):
    """An item of ``GET /v1/staff/journal/options``."""

    subject: SubjectRefResponse
    audience_key: str
    label: str


class ToggleResponse(BaseModel):
    """Result of a journal toggle."""

    attendance_version: int


class AttendanceRowResponse(BaseModel):
    """A row of ``AttendanceReport``."""

    key: str
    label: str
    absences: int
    excused: int
    lessons: int
    rate: float | None
    not_taken: int


class AttendanceReportResponse(BaseModel):
    """``AttendanceReport`` (the JSON keys are ``from`` and ``to``)."""

    model_config = ConfigDict(populate_by_name=True)

    view: str
    from_: dt.date = Field(alias="from")
    to: dt.date
    rows: list[AttendanceRowResponse]


class CuratorStudentResponse(BaseModel):
    """``CuratorStudent``."""

    user_id: UUID
    first_name: str
    last_name: str
    subgroup: Literal[1, 2] | None
    status: Literal["active", "left"]
    registered: bool
    absence_rate: float | None
    gpa: float | None
    flags: list[Literal["absences", "gpa_drop", "no_subgroup"]]


class SetHomeworkBody(BaseModel):
    """Body of ``PUT /v1/staff/lessons/{id}/homework``."""

    text: str
    due_date: dt.date | None = None


class SetTopicBody(BaseModel):
    """Body of ``PUT /v1/staff/lessons/{id}/topic``."""

    topic: str


class SubmitAttendanceBody(BaseModel):
    """Body of ``PUT /v1/staff/lessons/{id}/attendance``."""

    absent: list[UUID]
    late: list[UUID] = Field(default_factory=list)
    present_unassigned: list[UUID] = Field(default_factory=list)
    base_version: int


class ExcuseBody(BaseModel):
    """Body of ``PUT /v1/staff/lessons/{id}/attendance/excuse``."""

    student_id: UUID
    excused: bool
    comment: str | None = None


class ToggleBody(BaseModel):
    """Body of ``POST /v1/staff/journal/toggle``."""

    lesson_id: UUID
    student_id: UUID
    absent: bool
    late: bool = False
    base_version: int
