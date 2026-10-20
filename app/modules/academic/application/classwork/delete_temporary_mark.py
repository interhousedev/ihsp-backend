"""Use case: the lesson's teacher removes a student's temporary mark (TMP-1)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    TemporaryMarkUnitOfWork,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import TemporaryMarkNotFoundError
from app.shared.actor import Actor


class DeleteTemporaryMark:
    """Delete one student's temporary mark for a lesson."""

    def __init__(self, uow_factory: Callable[[], TemporaryMarkUnitOfWork]) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, lesson_id: UUID, student_id: UUID, actor: Actor) -> None:
        """Delete the mark.

        Raises:
            LessonNotFoundError: no such lesson.
            NotLessonTeacherError: the actor neither teaches the lesson nor is admin.
            TemporaryMarkNotFoundError: the student has no mark for the lesson.
        """
        async with self.uow_factory() as uow:
            ensure_lesson_staff(await require_lesson(uow, lesson_id), actor)
            if not await uow.temporary_marks.delete(lesson_id, student_id):
                raise TemporaryMarkNotFoundError(
                    params={"lesson_id": str(lesson_id), "student_id": str(student_id)}
                )
            await uow.commit()
