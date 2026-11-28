"""Response and request models of the staff classwork endpoints."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.me_classwork.schemas import (
    ExcuseRefResponse,
    HomeworkSource,
    LessonItemResponse,
    PersonRefResponse,
    ResourceItemResponse,
    ReviewStatus,
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
    excuse: ExcuseRefResponse | None = None
    excuse_comment: str | None
    counted: bool


class WorkOffResponse(BaseModel):
    """A work-off task given to one absent student (WO-3)."""

    id: UUID
    lesson_id: UUID
    student_id: UUID
    template_id: UUID | None
    text: str
    status: Literal["assigned", "done"]
    due_date: dt.date | None
    done_at: dt.datetime | None
    assigned_by: UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class AttendanceSheetResponse(BaseModel):
    """``AttendanceSheet``."""

    lesson_id: UUID
    submitted: bool
    version: int
    editable: bool
    roster: list[RosterItemResponse]
    submitted_at: dt.datetime | None
    submitted_by: PersonRefResponse | None
    work_offs: list[WorkOffResponse] = Field(default_factory=list)


class SubmissionCountsShortResponse(BaseModel):
    """How many students handed the homework in."""

    submitted: int
    total: int


class StaffHomeworkResponse(BaseModel):
    """Homework of a lesson as the teacher sees it.

    ``text`` is empty for homework that only EMIS gave; ``notify`` None follows the
    teacher's own setting, ``notify_effective`` is the value in force.
    """

    text: str
    source: HomeworkSource
    due_date: dt.date | None
    due_auto: bool
    accept_submissions: bool
    notify: bool | None
    notify_effective: bool
    emis_files: list[ResourceItemResponse]
    emis_topic_description: str | None
    submissions: SubmissionCountsShortResponse | None = None


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


class JournalTemporaryMarkResponse(BaseModel):
    """A temporary mark of a journal cell, not in EMIS yet (TMP-1)."""

    value: int
    comment: str | None


class JournalCellResponse(BaseModel):
    """A cell of the journal."""

    lesson_id: UUID
    absent: bool
    late: bool = False
    excused: bool
    excuse: ExcuseRefResponse | None = None
    marks: list[int]
    temporary_mark: JournalTemporaryMarkResponse | None = None


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
    """Body of ``PUT /v1/staff/lessons/{id}/homework``.

    ``text`` may be omitted when the lesson has EMIS homework; then only the due
    date and the switch change. ``accept_submissions`` omitted keeps the switch.
    """

    text: str | None = None
    due_date: dt.date | None = None
    accept_submissions: bool | None = None


class SetTopicBody(BaseModel):
    """Body of ``PUT /v1/staff/lessons/{id}/topic``."""

    topic: str


class CommonWorkOffBody(BaseModel):
    """One work-off choice: a template, a text or both, and a due date."""

    template_id: UUID | None = None
    text: str | None = None
    due_date: dt.date | None = None


class WorkOffChoiceBody(CommonWorkOffBody):
    """A work-off choice for one absent student."""

    student_id: UUID


class SubmitAttendanceBody(BaseModel):
    """Body of ``PUT /v1/staff/lessons/{id}/attendance``."""

    absent: list[UUID]
    late: list[UUID] = Field(default_factory=list)
    present_unassigned: list[UUID] = Field(default_factory=list)
    base_version: int
    work_off_mode: Literal["per_student", "none", "common"] = "per_student"
    work_offs: list[WorkOffChoiceBody] = Field(default_factory=list)
    common_work_off: CommonWorkOffBody | None = None


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


class StaffSubmissionFileResponse(BaseModel):
    """A handed-in file with a time-limited download link."""

    id: UUID
    name: str
    size: int
    content_type: str
    download_url: str


class StaffSubmissionRowResponse(BaseModel):
    """One student of the lesson, what they handed in and the review."""

    id: UUID | None
    student: PersonRefResponse
    group_name: str
    subgroup: int | None
    status: Literal["submitted", "late", "missing"]
    files: list[StaffSubmissionFileResponse]
    comment: str | None
    submitted_at: dt.datetime | None
    text: str | None
    review_status: ReviewStatus
    grade: int | None
    teacher_comment: str | None
    previous_comment: str | None
    reviewed_at: dt.datetime | None
    reviewer: PersonRefResponse | None


class SubmissionCountsResponse(BaseModel):
    """Totals over the lesson's students."""

    submitted: int
    late: int
    missing: int
    to_review: int
    graded: int
    returned: int
    total: int


class HomeworkSubmissionsResponse(BaseModel):
    """``HomeworkSubmissions``: the teacher's view of a lesson's homework."""

    lesson_id: UUID
    counts: SubmissionCountsResponse
    students: list[StaffSubmissionRowResponse]


class ReviewBody(BaseModel):
    """Body of ``PUT /v1/staff/homework/submissions/{submission_id}/review``.

    ``grade`` (2..5) is required for ``grade``, ``comment`` for ``return``.
    """

    action: Literal["grade", "return"]
    grade: int | None = None
    comment: str | None = None


class HomeworkSettingsResponse(BaseModel):
    """The teacher's own homework settings."""

    accept_by_default: bool
    notify_on_submission: bool


class HomeworkSettingsBody(BaseModel):
    """Body of ``PUT /v1/staff/homework/settings``; an omitted field is kept."""

    accept_by_default: bool | None = None
    notify_on_submission: bool | None = None


class LessonHomeworkSwitchesBody(BaseModel):
    """Body of ``PATCH /v1/staff/lessons/{id}/homework/settings``.

    An omitted field is kept; ``notify: null`` follows the teacher's setting again.
    """

    accept_submissions: bool | None = None
    notify: bool | None = None


class BoardHomeworkResponse(BaseModel):
    """Homework of a board lesson."""

    text: str
    due_date: dt.date | None
    due_auto: bool
    source: HomeworkSource


class BoardCountsResponse(BaseModel):
    """Submission counts of a board lesson; ``total`` is the expected roster."""

    submitted: int
    late: int
    missing: int
    to_review: int
    graded: int
    total: int


class BoardLessonResponse(BaseModel):
    """A lesson of the homework board."""

    lesson_id: UUID
    date: dt.date
    period: int
    topic: str | None
    emis_topic_description: str | None
    emis_files: list[ResourceItemResponse]
    homework: BoardHomeworkResponse | None
    accept_submissions: bool
    notify: bool | None
    notify_effective: bool
    counts: BoardCountsResponse | None


class StaffHomeworkBoardResponse(BaseModel):
    """``StaffHomeworkBoard``: the lessons of one journal option, newest first."""

    subject: SubjectRefResponse
    audience_key: str
    label: str
    lessons: list[BoardLessonResponse]
    settings: HomeworkSettingsResponse
