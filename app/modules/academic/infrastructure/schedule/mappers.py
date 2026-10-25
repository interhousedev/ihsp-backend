"""Mapping ORM rows to schedule entities and back (CODESTYLE: _to_entity / _apply)."""

from typing import Any, cast

from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.room import Room
from app.modules.academic.domain.schedule.student import Student
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.domain.schedule.term import (
    Term,
    bells_from_json,
    bells_to_json,
    control_periods_from_json,
    control_periods_to_json,
    moved_days_from_json,
    moved_days_to_json,
)
from app.modules.academic.domain.schedule.timetable_entry import (
    TimetableEntry,
    WeekParity,
)
from app.modules.academic.infrastructure.orm import Group as GroupRow
from app.modules.academic.infrastructure.orm import Lesson as LessonRow
from app.modules.academic.infrastructure.orm import Room as RoomRow
from app.modules.academic.infrastructure.orm import Student as StudentRow
from app.modules.academic.infrastructure.orm import Subject as SubjectRow
from app.modules.academic.infrastructure.orm import Term as TermRow
from app.modules.academic.infrastructure.orm import TimetableEntry as EntryRow

# - - - Terms - - -


def term_to_entity(row: TermRow) -> Term:
    """Map a term row, validating its jsonb columns."""
    return Term(
        id=row.id,
        academic_year=row.academic_year,
        half=row.half,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        bells=bells_from_json(row.bells),
        non_study_days=list(row.non_study_days or []),
        moved_days=moved_days_from_json(row.moved_days),
        control_periods=control_periods_from_json(row.control_periods),
    )


def term_apply(row: TermRow, term: Term) -> None:
    """Copy the term's fields onto the row."""
    row.academic_year = term.academic_year
    row.half = term.half
    row.starts_on = term.starts_on
    row.ends_on = term.ends_on
    row.bells = bells_to_json(term.bells)
    row.non_study_days = list(term.non_study_days)
    row.moved_days = moved_days_to_json(term.moved_days)
    row.control_periods = control_periods_to_json(term.control_periods)


def term_new_row(term: Term) -> TermRow:
    """Create a row for a new term."""
    row = TermRow(id=term.id)
    term_apply(row, term)
    return row


# - - - Groups - - -


def group_to_entity(row: GroupRow) -> Group:
    """Map a group row."""
    return Group(
        id=row.id,
        name=row.name,
        slug=row.slug,
        emis_group_id=row.emis_group_id,
        current_semester=row.current_semester,
        emis_curriculum_id=row.emis_curriculum_id,
        subject_ids=list(row.subject_ids or []),
        curator_id=row.curator_id,
        head_student_id=row.head_student_id,
        status=cast(Any, row.status),
    )


def group_apply(row: GroupRow, group: Group) -> None:
    """Copy the group's fields onto the row."""
    row.emis_group_id = group.emis_group_id
    row.name = group.name
    row.slug = group.slug
    row.current_semester = group.current_semester
    row.emis_curriculum_id = group.emis_curriculum_id
    row.subject_ids = list(group.subject_ids)
    row.curator_id = group.curator_id
    row.head_student_id = group.head_student_id
    row.status = group.status


def group_new_row(group: Group) -> GroupRow:
    """Create a row for a new group."""
    row = GroupRow(id=group.id)
    group_apply(row, group)
    return row


# - - - Students - - -


def student_to_entity(row: StudentRow) -> Student:
    """Map a student row."""
    return Student(
        user_id=row.user_id,
        group_id=row.group_id,
        subgroup=row.subgroup,
        subgroup_set_by=row.subgroup_set_by,
        subgroup_set_at=row.subgroup_set_at,
        status=cast(Any, row.status),
        left_at=row.left_at,
        left_reason=row.left_reason,
        synced_at=row.synced_at,
    )


def student_apply(row: StudentRow, student: Student) -> None:
    """Copy the schedule fields of the student onto the row."""
    row.group_id = student.group_id
    row.subgroup = student.subgroup
    row.subgroup_set_by = student.subgroup_set_by
    row.subgroup_set_at = student.subgroup_set_at
    row.status = student.status
    row.left_at = student.left_at
    row.left_reason = student.left_reason


def student_new_row(student: Student) -> StudentRow:
    """Create a row for a new student."""
    row = StudentRow(user_id=student.user_id)
    student_apply(row, student)
    return row


# - - - Subjects and rooms - - -


def subject_to_entity(row: SubjectRow) -> Subject:
    """Map a subject row."""
    return Subject(
        id=row.id,
        name={str(k): str(v) for k, v in (row.name or {}).items()},
        short_name=row.short_name,
        emis_subject_id=row.emis_subject_id,
        can_be_divided=bool(row.can_be_divided),
    )


def subject_apply(row: SubjectRow, subject: Subject) -> None:
    """Copy the subject's fields onto the row."""
    row.name = dict(subject.name)
    row.short_name = subject.short_name
    row.emis_subject_id = subject.emis_subject_id
    row.can_be_divided = subject.can_be_divided


def subject_new_row(subject: Subject) -> SubjectRow:
    """Create a row for a new subject."""
    row = SubjectRow(id=subject.id)
    subject_apply(row, subject)
    return row


def room_to_entity(row: RoomRow) -> Room:
    """Map a room row."""
    return Room(
        id=row.id,
        slug=row.slug,
        name=row.name,
        pin=row.pin,
        pin_changed_at=row.pin_changed_at,
        status=cast(Any, row.status),
        merged_into_id=row.merged_into_id,
    )


def room_apply(row: RoomRow, room: Room) -> None:
    """Copy the room's fields onto the row."""
    row.slug = room.slug
    row.name = room.name
    row.pin = room.pin
    row.pin_changed_at = room.pin_changed_at
    row.status = room.status
    row.merged_into_id = room.merged_into_id


def room_new_row(room: Room) -> RoomRow:
    """Create a row for a new room."""
    row = RoomRow(id=room.id)
    room_apply(row, room)
    return row


# - - - Timetable entries - - -


def entry_to_entity(row: EntryRow) -> TimetableEntry:
    """Map a timetable entry row."""
    parity: WeekParity = cast(Any, row.week_parity)
    return TimetableEntry(
        id=row.id,
        term_id=row.term_id,
        weekday=row.weekday,
        period=row.period,
        week_parity=parity,
        subject_id=row.subject_id,
        teacher_id=row.teacher_id,
        room_id=row.room_id,
        audience=list(row.audience or []),
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        source=cast(Any, row.source),
    )


def entry_apply(row: EntryRow, entry: TimetableEntry) -> None:
    """Copy the entry's fields onto the row."""
    row.term_id = entry.term_id
    row.weekday = entry.weekday
    row.period = entry.period
    row.week_parity = entry.week_parity
    row.subject_id = entry.subject_id
    row.teacher_id = entry.teacher_id
    row.room_id = entry.room_id
    row.audience = list(entry.audience)
    row.valid_from = entry.valid_from
    row.valid_to = entry.valid_to
    row.source = entry.source


def entry_new_row(entry: TimetableEntry) -> EntryRow:
    """Create a row for a new entry."""
    row = EntryRow(id=entry.id)
    entry_apply(row, entry)
    return row


# - - - Lessons - - -


def lesson_to_entity(row: LessonRow, *, has_content: bool = False) -> Lesson:
    """Map a lesson row (schedule columns only)."""
    return Lesson(
        id=row.id,
        term_id=row.term_id,
        date=row.date,
        period=row.period,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        subject_id=row.subject_id,
        teacher_id=row.teacher_id,
        room_id=row.room_id,
        audience=list(row.audience or []),
        status=cast(Any, row.status),
        is_overridden=bool(row.is_overridden),
        timetable_entry_id=row.timetable_entry_id,
        origin_date=row.origin_date,
        topic=row.topic,
        changes=dict(row.changes) if row.changes else None,
        has_content=has_content,
        kind=cast(Any, row.kind),
        emis_class_id=row.emis_class_id,
        emis_topic=row.emis_topic,
    )


def lesson_apply(row: LessonRow, lesson: Lesson) -> None:
    """Copy the schedule columns of the lesson onto the row."""
    row.timetable_entry_id = lesson.timetable_entry_id
    row.origin_date = lesson.origin_date
    row.term_id = lesson.term_id
    row.date = lesson.date
    row.period = lesson.period
    row.starts_at = lesson.starts_at
    row.ends_at = lesson.ends_at
    row.subject_id = lesson.subject_id
    row.teacher_id = lesson.teacher_id
    row.room_id = lesson.room_id
    row.topic = lesson.topic
    row.audience = list(lesson.audience)
    row.changes = lesson.changes
    row.status = lesson.status
    row.is_overridden = lesson.is_overridden
    row.kind = lesson.kind
    row.emis_class_id = lesson.emis_class_id
    row.emis_topic = lesson.emis_topic


def lesson_new_row(lesson: Lesson) -> LessonRow:
    """Create a row for a new lesson."""
    row = LessonRow(id=lesson.id)
    lesson_apply(row, lesson)
    return row
