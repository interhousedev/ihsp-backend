"""Use case: the student ticks or unticks a homework item (WEB-19)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.homework_items import (
    HomeworkItemBuilder,
)
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    TodoUnitOfWork,
)
from app.modules.academic.application.classwork.student_context import (
    keys_of,
    require_student,
)
from app.modules.academic.domain.classwork.errors import (
    HomeworkNotFoundError,
    LessonNotFoundError,
)
from app.modules.academic.domain.classwork.records import HomeworkRecord
from app.shared.actor import Actor
from app.shared.clock import Clock


class SetHomeworkDone:
    """Personal tracking only; nobody else sees ticks (UF-WEB-13)."""

    def __init__(
        self,
        uow_factory: Callable[[], TodoUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        items: HomeworkItemBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.items = items

    async def execute(
        self, lesson_id: UUID, actor: Actor, done: bool
    ) -> dict[str, Any]:
        """Tick or untick and return the updated ``HomeworkItem``."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            lesson = await uow.lesson_reader.visible_lesson(keys_of(student), lesson_id)
            if lesson is None:
                raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})
            if not lesson.has_homework:
                raise HomeworkNotFoundError(params={"lesson_id": str(lesson_id)})
            todo = await uow.todos.upsert_done(
                student.user_id, lesson_id, now if done else None, now
            )
            await uow.commit()
        locale = await self.people.locale(actor.user_id)
        built = await self.items.build_many([HomeworkRecord(lesson, todo)], locale)
        return built[0]
