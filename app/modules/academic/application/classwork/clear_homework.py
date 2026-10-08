"""Use case: the teacher removes a lesson's homework (STF-7)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    LessonUnitOfWork,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.lesson import Lesson
from app.shared.actor import Actor
from app.shared.clock import Clock


class ClearHomework:
    """Remove the homework from the students' lists."""

    def __init__(
        self, uow_factory: Callable[[], LessonUnitOfWork], clock: Clock
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, lesson_id: UUID, actor: Actor) -> Lesson:
        """Clear the homework and return the updated lesson."""
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_lesson_staff(lesson, actor)
            await uow.lessons.clear_homework(lesson_id, self.clock.now())
            await uow.commit()
            return await require_lesson(uow, lesson_id)
