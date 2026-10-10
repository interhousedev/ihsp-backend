"""Response models of the student marks endpoints (§ API contract -> Schemas)."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.shared.lesson_kind import LessonKind, TopicSource

from pydantic import BaseModel

MarkType = Literal["lesson", "midterm", "final"]
AttendanceValue = Literal["present", "late", "absent", "excused", "not_taken"]


class PersonRef(BaseModel):
    """A person: id, names and, for the teachers of a subject, a photo."""

    id: UUID
    first_name: str
    last_name: str
    photo_url: str | None = None


class SubjectRef(BaseModel):
    """A subject named in the caller's locale."""

    id: UUID
    name: str
    short_name: str


class RoomRefLite(BaseModel):
    """A room: id, slug and name."""

    id: UUID
    slug: str | None
    name: str | None


class AudienceItem(BaseModel):
    """A group or subgroup a lesson is for."""

    group_id: UUID
    group_name: str
    subgroup: Literal[1, 2] | None


class MarkItem(BaseModel):
    """One mark."""

    subject: SubjectRef
    semester: int
    type: MarkType
    value: int
    date: dt.date
    lesson_id: UUID | None


class LessonItem(BaseModel):
    """A lesson in lists."""

    id: UUID
    date: dt.date
    period: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject: SubjectRef
    teacher: PersonRef | None
    room: RoomRefLite | None
    audience: list[AudienceItem]
    status: Literal["scheduled", "cancelled"]
    is_overridden: bool
    changes: dict[str, Any] | None
    topic: str | None
    kind: LessonKind = "other"
    # "emis": the topic came from EMIS (a hint); "manual": a person wrote it.
    topic_source: TopicSource | None = None
    has_homework: bool
    attendance_submitted: bool


class SubjectLesson(LessonItem):
    """A lesson on a subject page with the student's marks and attendance."""

    marks: list[MarkItem]
    attendance: AttendanceValue
    homework_text: str | None


class ResourceItem(BaseModel):
    """A material or attachment of a lesson."""

    link_id: UUID
    lesson_id: UUID
    role: Literal["material", "attachment", "homework"]
    kind: Literal["url", "file"]
    short_url: str
    title: str
    author: PersonRef
    hidden: bool
    file: dict[str, Any] | None
    created_at: dt.datetime | None
    source: Literal["user", "emis"] = "user"


class SubjectCardResponse(BaseModel):
    """A subject in the list of a semester."""

    subject: SubjectRef
    teachers: list[PersonRef]
    semester_mark: float | None
    emis_rating: int | None
    absences: int
    lates: int = 0
    next_lesson: LessonItem | None


class Averages(BaseModel):
    """Lesson, midterm and final averages."""

    lesson: float | None
    midterm: float | None
    final: float | None


class SubjectDetailResponse(BaseModel):
    """One subject of a semester with lessons, marks and materials."""

    subject: SubjectRef
    semester: int
    teachers: list[PersonRef]
    averages: Averages
    semester_mark: float | None
    emis_rating: int | None
    absence_rate: float | None
    lessons: list[SubjectLesson]
    marks: list[MarkItem]
    materials: list[ResourceItem]


class GradeRow(BaseModel):
    """A subject row of the grade table."""

    subject: SubjectRef
    lesson_avg: float | None
    midterm_avg: float | None
    final_avg: float | None
    semester_mark: float | None
    emis_rating: int | None
    marks_count: int


class SemesterGradesResponse(BaseModel):
    """The grade table of a semester."""

    semester: int
    gpa: float | None
    synced_at: dt.datetime | None
    rows: list[GradeRow]


class DayLessonMarks(BaseModel):
    """A lesson of the day with the marks matched to it."""

    lesson: LessonItem
    marks: list[MarkItem]


class DayGradesResponse(BaseModel):
    """The marks of one date."""

    date: dt.date
    lessons: list[DayLessonMarks]
    unmatched: list[MarkItem]


class RecordBookSubject(BaseModel):
    """A subject in one semester of the record book."""

    subject: SubjectRef
    semester_mark: float | None
    emis_rating: int | None


class RecordBookSemester(BaseModel):
    """One semester of the record book."""

    semester: int
    gpa: float | None
    subjects: list[RecordBookSubject]


class RecordBookResponse(BaseModel):
    """All semesters with results."""

    semesters: list[RecordBookSemester]


class SubjectLessonMark(BaseModel):
    """One mark placed on a lesson of the subject hub list."""

    type: Literal["lesson", "midterm", "final"]
    value: int


class SubjectLessonRow(BaseModel):
    """One row of the subject hub lesson list."""

    lesson_id: UUID
    date: dt.date
    starts_at: dt.datetime
    kind: LessonKind = "other"
    topic: str | None
    marks: list[SubjectLessonMark]
    attendance: Literal["present", "absent", "late"] | None
    materials_count: int
    past: bool


class SubjectLessonListResponse(BaseModel):
    """Latest past lessons first, then the upcoming ones."""

    items: list[SubjectLessonRow]
    has_more_past: bool


class LessonResultRow(BaseModel):
    """Attendance and mark of one lesson that has started (calendar dot)."""

    lesson_id: UUID
    attendance: Literal["present", "absent", "late"] | None
    mark: int | None
