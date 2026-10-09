"""Response models shared by the composition endpoints (§ API contract -> Schemas)."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.shared.lesson_kind import LessonKind, TopicSource

from pydantic import BaseModel, ConfigDict, Field

RoleName = Literal["student", "teacher", "admin", "lms_admin", "librarian"]


class PersonRefResponse(BaseModel):
    """`PersonRef`."""

    id: UUID
    first_name: str
    last_name: str


class SubjectRefResponse(BaseModel):
    """`SubjectRef`."""

    id: UUID
    name: str
    short_name: str


class RoomRefLiteResponse(BaseModel):
    """`RoomRefLite`."""

    id: UUID
    slug: str | None
    name: str | None


class AudienceItemResponse(BaseModel):
    """`AudienceItem`: a group or a subgroup."""

    group_id: UUID
    group_name: str
    subgroup: Literal[1, 2] | None


class LessonItemResponse(BaseModel):
    """`LessonItem`."""

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
    # Record<string, [unknown, unknown]>: old and new value of each changed field.
    changes: dict[str, Any] | None
    topic: str | None
    kind: LessonKind = "other"
    # "emis": the topic came from EMIS (a hint); "manual": a person wrote it.
    topic_source: TopicSource | None = None
    has_homework: bool
    attendance_submitted: bool


class HomeworkItemResponse(BaseModel):
    """`HomeworkItem`."""

    lesson_id: UUID
    subject: SubjectRefResponse
    teacher: PersonRefResponse | None
    text: str
    due_date: dt.date | None
    given_on: dt.date
    updated: bool
    done_at: dt.datetime | None
    note: str | None


class GroupRefResponse(BaseModel):
    """A group as `{id, name}`."""

    id: UUID
    name: str


class StudentProfileResponse(BaseModel):
    """`StudentProfile`."""

    user_id: UUID
    login: str | None
    first_name: str
    last_name: str
    mailbox: str | None
    group: GroupRefResponse
    subgroup: Literal[1, 2] | None
    curator: PersonRefResponse | None
    head_student: PersonRefResponse | None
    current_semester: int | None
    emis_status: str | None
    synced_at: dt.datetime | None


class GradeRowResponse(BaseModel):
    """A row of `SemesterGrades`."""

    subject: SubjectRefResponse
    lesson_avg: float | None
    midterm_avg: float | None
    final_avg: float | None
    semester_mark: float | None
    emis_rating: int | None
    marks_count: int


class SemesterGradesResponse(BaseModel):
    """`SemesterGrades`."""

    semester: int
    gpa: float | None
    synced_at: dt.datetime | None
    rows: list[GradeRowResponse]


class SubjectAttendanceResponse(BaseModel):
    """A row of `StudentAttendance.summary`."""

    subject: SubjectRefResponse
    absences: int
    excused: int
    lessons: int
    rate: float | None


class AbsenceDayResponse(BaseModel):
    """A row of `StudentAttendance.days`."""

    date: dt.date
    absences: int


class MissedLessonResponse(BaseModel):
    """A row of `StudentAttendance.missed`."""

    lesson: LessonItemResponse
    excused: bool


class StudentAttendanceResponse(BaseModel):
    """`StudentAttendance` (the JSON keys are `from` and `to`)."""

    model_config = ConfigDict(populate_by_name=True)

    from_: dt.date = Field(alias="from")
    to: dt.date
    summary: list[SubjectAttendanceResponse]
    days: list[AbsenceDayResponse]
    missed: list[MissedLessonResponse]
    not_taken: int


class TelegramAccountResponse(BaseModel):
    """`TelegramAccount`."""

    telegram_user_id: int
    username: str | None
    otp_delivery: bool
    blocked: bool
    linked_at: dt.datetime


class SessionItemResponse(BaseModel):
    """`SessionItem`."""

    id: UUID
    ip: str | None
    user_agent: str | None
    amr: list[str]
    last_seen_at: dt.datetime
    current: bool


class AuditItemResponse(BaseModel):
    """`AuditItem`."""

    id: UUID
    type: str
    ip: str | None
    user_agent: str | None
    actor: PersonRefResponse | None
    created_at: dt.datetime
    # Free-form event details; the shape depends on the event type.
    metadata: dict[str, Any]


class AdminUserResponse(BaseModel):
    """`AdminUser`."""

    id: UUID
    login: str | None
    first_name: str
    last_name: str
    middle_name: str | None
    roles: list[RoleName]
    status: str
    emis_status: str | None
    recovery_email: str | None
    mail_suspended: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None


class GroupItemResponse(BaseModel):
    """`GroupItem`."""

    id: UUID
    name: str
    slug: str
    current_semester: int | None
    status: Literal["active", "archived"]
    students_count: int
    subgroups_assigned: int
    unregistered_count: int
    curator: PersonRefResponse | None
    head_student: PersonRefResponse | None
