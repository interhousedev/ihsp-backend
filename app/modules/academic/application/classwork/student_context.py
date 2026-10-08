"""Shared helpers for use cases that act as a student."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.ports.lesson_reader import LessonReader
from app.modules.academic.application.classwork.ports.unit_of_work import (
    TodoUnitOfWork,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.classwork.errors import StudentNotFoundError
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.names import localized
from app.modules.academic.domain.classwork.records import MarkRecord, StudentRecord
from app.shared.contracts.academic import ScheduleQueries

PROJECTION_DAYS = 30


async def require_student(uow: TodoUnitOfWork, user_id: UUID) -> StudentRecord:
    """Return the caller's student record or raise StudentNotFoundError."""
    student = await uow.students.get(user_id)
    if student is None:
        raise StudentNotFoundError(params={"user_id": str(user_id)})
    return student


def keys_of(student: StudentRecord) -> list[str]:
    """Audience keys that match the student (both subgroups when not set)."""
    return audience_keys.student_keys(student.group_id, student.subgroup)


class StudyDays:
    """Finds the next study day, looking past the generated lessons if needed."""

    def __init__(self, schedule: ScheduleQueries) -> None:
        """Store the schedule queries."""
        self.schedule = schedule

    async def next_after(
        self,
        reader: LessonReader,
        student_id: UUID,
        keys: list[str],
        after: dt.date,
    ) -> dt.date | None:
        """Earliest date after ``after`` with a scheduled lesson for the student."""
        found = await reader.next_study_day(keys, after)
        if found is not None:
            return found
        projected = await self.schedule.projected_lessons_for_student(
            student_id,
            after + dt.timedelta(days=1),
            after + dt.timedelta(days=PROJECTION_DAYS),
        )
        dates = [lesson.date for lesson in projected if lesson.status == "scheduled"]
        return min(dates) if dates else None


def attendance_state(lesson: Lesson, student_id: UUID) -> str:
    """present, absent, excused or not_taken for one student (WEB-9)."""
    if lesson.attendance_absent is None:
        return "not_taken"
    if student_id in lesson.attendance_absent:
        return "excused" if str(student_id) in lesson.excused_ids() else "absent"
    if student_id in (lesson.attendance_roster or ()):
        return "present"
    return "not_taken"


def mark_item(mark: MarkRecord, locale: str) -> dict[str, Any]:
    """Build the ``MarkItem`` JSON of a mark."""
    name = localized(mark.subject_names, locale)
    return {
        "subject": {
            "id": str(mark.subject_id),
            "name": name,
            "short_name": mark.subject_short or name,
        },
        "semester": mark.semester,
        "type": mark.type,
        "value": mark.value,
        "date": mark.date.isoformat(),
        "lesson_id": None if mark.lesson_id is None else str(mark.lesson_id),
    }
