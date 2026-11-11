"""Use case: the teacher sees who handed in the homework of a lesson."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.application.classwork.submission_views import (
    SubmissionViewBuilder,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import HomeworkNotFoundError
from app.modules.academic.domain.classwork.submission_rules import submission_status
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
        students = [*roster.expected] + [
            s for s in roster.unassigned if s.user_id in records
        ]
        rows = []
        counts = {"submitted": 0, "late": 0, "missing": 0}
        for student in students:
            record = records.get(student.user_id)
            status = submission_status(
                record.submitted_at if record else None, lesson.homework_due_date
            )
            counts[status] += 1
            rows.append(
                {
                    "student": {
                        "id": str(student.user_id),
                        "first_name": student.first_name,
                        "last_name": student.last_name,
                    },
                    "group_name": student.group_name,
                    "subgroup": student.subgroup,
                    "status": status,
                    "files": (
                        [files[i] for i in record.file_ids if i in files]
                        if record
                        else []
                    ),
                    "comment": record.comment if record else None,
                    "submitted_at": (
                        record.submitted_at.isoformat() if record else None
                    ),
                }
            )
        return {
            "lesson_id": str(lesson_id),
            "counts": {**counts, "total": len(rows)},
            "students": rows,
        }
