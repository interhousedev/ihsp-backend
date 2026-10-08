"""Read models returned by the schedule use cases (HTTP maps them to schemas)."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.domain.schedule.term import Bell, MovedDay


@dataclass(frozen=True, slots=True)
class PersonData:
    """PersonRef: id and names."""

    id: UUID
    first_name: str
    last_name: str


@dataclass(frozen=True, slots=True)
class SubjectRefData:
    """SubjectRef: name in the caller's locale."""

    id: UUID
    name: str
    short_name: str | None


@dataclass(frozen=True, slots=True)
class RoomLiteData:
    """RoomRefLite."""

    id: UUID
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class AudienceItemData:
    """AudienceItem: a group and an optional subgroup."""

    group_id: UUID
    group_name: str
    subgroup: int | None


@dataclass(frozen=True, slots=True)
class TermData:
    """Term with the is_current flag."""

    id: UUID
    academic_year: str
    half: int
    starts_on: dt.date
    ends_on: dt.date
    bells: list[Bell]
    non_study_days: list[dt.date]
    moved_days: list[MovedDay]
    is_current: bool


@dataclass(frozen=True, slots=True)
class GroupItemData:
    """GroupItem: a list row of groups."""

    id: UUID
    name: str
    slug: str
    current_semester: int | None
    status: Literal["active", "archived"]
    students_count: int
    subgroups_assigned: int
    unregistered_count: int
    curator: PersonData | None
    head_student: PersonData | None


@dataclass(frozen=True, slots=True)
class GroupStudentData:
    """GroupStudent: one student in a group."""

    user_id: UUID
    first_name: str
    last_name: str
    subgroup: int | None
    status: Literal["active", "left"]
    registered: bool


@dataclass(frozen=True, slots=True)
class GroupDetailData:
    """GroupDetail: GroupItem plus the roster."""

    id: UUID
    name: str
    slug: str
    current_semester: int | None
    status: Literal["active", "archived"]
    students_count: int
    subgroups_assigned: int
    unregistered_count: int
    curator: PersonData | None
    head_student: PersonData | None
    emis_group_id: int | None
    students: list[GroupStudentData]


@dataclass(frozen=True, slots=True)
class RoomData:
    """Room with its page URL and this week's lessons."""

    id: UUID
    slug: str
    name: str
    pin: str
    url: str
    status: Literal["active", "archived"]
    lessons_this_week: int


@dataclass(frozen=True, slots=True)
class TimetableEntryData:
    """TimetableEntry with names resolved."""

    id: UUID
    term_id: UUID
    weekday: int
    period: int
    week_parity: Literal["every", "odd", "even"]
    subject: SubjectRefData
    teacher: PersonData | None
    room: RoomLiteData | None
    audience: list[AudienceItemData]
    valid_from: dt.date
    valid_to: dt.date | None


@dataclass(frozen=True, slots=True)
class ConflictData:
    """Conflict as returned by the check endpoint."""

    kind: Literal["teacher", "room", "audience"]
    with_entry_id: UUID | None
    with_lesson_id: UUID | None
    description: str


@dataclass(frozen=True, slots=True)
class StudentItemData:
    """StudentItem: a row of the admin student list."""

    user_id: UUID
    login: str | None
    first_name: str
    last_name: str
    group_id: UUID | None
    group_name: str | None
    subgroup: int | None
    status: str
    emis_status: str | None
    registered: bool
    synced_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class StudentProfileData:
    """StudentProfile of the logged-in student."""

    user_id: UUID
    login: str | None
    first_name: str
    last_name: str
    mailbox: str | None
    group_id: UUID
    group_name: str
    subgroup: int | None
    curator: PersonData | None
    head_student: PersonData | None
    current_semester: int | None
    emis_status: str | None
    synced_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class ImportRowData:
    """ImportRow of a preview."""

    line: int
    last_name: str
    first_name: str
    middle_name: str | None
    group_name: str
    emis_student_id: int | None
    note: str | None


@dataclass(frozen=True, slots=True)
class ImportPreviewData:
    """ImportPreview: rows grouped by what confirmation will do."""

    import_id: UUID
    new: list[ImportRowData]
    changed: list[ImportRowData]
    unchanged: int
    conflicts: list[ImportRowData]


@dataclass(frozen=True, slots=True)
class ImportResultData:
    """Result of confirming an import."""

    created: int
    updated: int
    skipped: int


@dataclass(frozen=True, slots=True)
class LessonItemsPage:
    """A page of LessonItem dicts (shape of ``lesson_item``)."""

    items: list[dict[str, Any]]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class StudentsPage:
    """A page of the admin student list."""

    items: list[StudentItemData]
    next_cursor: str | None
