"""Show one student's record in a subject to its teacher (UF-STF-06)."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.teaching.access import taught_group
from app.modules.academic.application.teaching.get_teaching_group import roster_rows
from app.modules.academic.application.teaching.views import (
    AbsentLesson,
    HomeworkEntry,
    TeachingStudentView,
)
from app.modules.academic.domain.schedule.errors import StudentNotInGroupError
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import (
    ClassworkQueries,
    LessonRef,
    MarkRef,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.identity import IdentityDirectory


def newest_semester(marks: list[MarkRef]) -> tuple[int | None, list[MarkRef]]:
    """The newest semester with marks and its marks (the scale is 2 to 5)."""
    if not marks:
        return None, []
    semester = max(m.semester for m in marks)
    return semester, [m for m in marks if m.semester == semester]


def average(marks: list[MarkRef]) -> float | None:
    """The mean of the marks on the 5-point scale, two decimals."""
    if not marks:
        return None
    return round(sum(m.value for m in marks) / len(marks), 2)


def _homework(items: list[dict[str, Any]], subject_id: UUID) -> list[HomeworkEntry]:
    entries = []
    for item in items:
        lesson: LessonRef = item["lesson"]
        if lesson.subject_id != subject_id:
            continue
        entries.append(
            HomeworkEntry(
                lesson_id=lesson.id,
                date=lesson.date,
                due_date=lesson.homework_due_date,
                text=lesson.homework_text,
                done_at=item.get("done_at"),
                note=item.get("note"),
            )
        )
    entries.sort(key=lambda e: e.due_date or e.date, reverse=True)
    return entries


def _absent(items: list[dict[str, Any]], subject_id: UUID) -> list[AbsentLesson]:
    found = [
        AbsentLesson(
            lesson_id=item["lesson"].id,
            date=item["lesson"].date,
            excused=bool(item.get("excused")),
        )
        for item in items
        if item["lesson"].subject_id == subject_id
    ]
    return sorted(found, key=lambda a: a.date, reverse=True)


class GetTeachingStudent:
    """Marks, homework and attendance of a student of a taught subject group."""

    def __init__(
        self,
        *,
        schedule: ScheduleQueries,
        identity: IdentityDirectory,
        marks: MarksQueries,
        classwork: ClassworkQueries,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.schedule = schedule
        self.identity = identity
        self.marks = marks
        self.classwork = classwork
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        subject_id: UUID,
        group_id: UUID,
        student_id: UUID,
        subgroup: int | None,
    ) -> TeachingStudentView:
        """Return the record; 403 when the caller does not teach the group."""
        group = await taught_group(
            self.schedule,
            actor,
            subject_id,
            group_id,
            subgroup,
            local_today(self.clock),
        )
        student = next((s for s in group.students if s.user_id == student_id), None)
        if student is None:
            raise StudentNotInGroupError()
        semester, marks = newest_semester(
            await self.marks.marks(student_id, subject_id, None, None)
        )
        summary = next(
            (
                s
                for s in await self.marks.subjects_summary(student_id, None)
                if s.subject_id == subject_id
            ),
            None,
        )
        absent = _absent(
            await self.classwork.absences(student_id, None, None), subject_id
        )
        return TeachingStudentView(
            subject_id=subject_id,
            subject_name=group.subject_name or (summary.name if summary else ""),
            group_id=group_id,
            group_name=group.group_name,
            student=(await roster_rows(self.identity, [student]))[0],
            semester=semester,
            marks=marks,
            average=average(marks),
            semester_mark=summary.semester_mark if summary else None,
            homework=_homework(
                await self.classwork.homework(student_id, None, None, None),
                subject_id,
            ),
            absences=len(absent),
            lessons_with_attendance=(
                summary.lessons_with_attendance if summary else None
            ),
            absent_lessons=absent,
            gpa_with_temporary=summary.gpa_with_temporary if summary else None,
        )
