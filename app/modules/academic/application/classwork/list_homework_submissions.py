"""Use case: the teacher sees who handed in the homework of a lesson."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.people import Person
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.application.classwork.submission_views import (
    SubmissionViewBuilder,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import HomeworkNotFoundError
from app.shared.actor import Actor


class ListHomeworkSubmissions:
    """Every student of the lesson with the status and the handed-in files."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        roster_loader: RosterLoader,
        views: SubmissionViewBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.roster_loader = roster_loader
        self.views = views

    async def execute(self, lesson_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return ``HomeworkSubmissions``: counts and one row per student.

        Raises:
            NotLessonTeacherError: The caller is neither the teacher nor an admin.
            HomeworkNotFoundError: The lesson has no homework.
        """
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_lesson_staff(lesson, actor)
            if not lesson.has_homework:
                raise HomeworkNotFoundError(params={"lesson_id": str(lesson_id)})
            roster = await self.roster_loader.load(uow, lesson)
            stored = await uow.submissions.for_lesson(lesson_id)
            records = {s.student_id: s for s in stored}
        files = await self.views.teacher_files(list(records.values()))
        reviewers = await self.views.people.people(
            r.reviewed_by for r in records.values() if r.reviewed_by
        )
        students = [*roster.expected] + [
            s for s in roster.unassigned if s.user_id in records
        ]
        rows = []
        counts = {
            "submitted": 0,
            "late": 0,
            "missing": 0,
            "to_review": 0,
            "graded": 0,
            "returned": 0,
        }
        for student in students:
            record = records.get(student.user_id)
            row = self.views.teacher_row(
                student=Person(student.user_id, student.first_name, student.last_name),
                group_name=student.group_name,
                subgroup=student.subgroup,
                record=record,
                due=lesson.homework_due_date,
                files=files,
                reviewers=reviewers,
            )
            counts[row["status"]] += 1
            if record is not None:
                if record.review_status == "pending":
                    counts["to_review"] += 1
                elif record.review_status == "graded":
                    counts["graded"] += 1
                else:
                    counts["returned"] += 1
            rows.append(row)
        return {
            "lesson_id": str(lesson_id),
            "counts": {**counts, "total": len(rows)},
            "students": rows,
        }
