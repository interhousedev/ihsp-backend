"""Use case: the teacher sets the lesson topic (ACA-21)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    LessonUnitOfWork,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.homework_rules import clean_topic
from app.modules.academic.domain.classwork.lesson import Lesson
from app.shared.actor import Actor
from app.shared.clock import Clock


class SetTopic:
    """Save the topic; an empty topic clears it."""

    def __init__(
        self, uow_factory: Callable[[], LessonUnitOfWork], clock: Clock
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, lesson_id: UUID, actor: Actor, topic: str) -> Lesson:
        """Save the topic and return the updated lesson."""
        clean = clean_topic(topic)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_lesson_staff(lesson, actor)
            await uow.lessons.set_topic(lesson_id, clean, self.clock.now())
            await uow.commit()
            return await require_lesson(uow, lesson_id)
