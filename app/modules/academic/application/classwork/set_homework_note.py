"""Use case: the student saves a private note on a homework item (WEB-20)."""

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
from app.modules.academic.domain.classwork.errors import LessonNotFoundError
from app.modules.academic.domain.classwork.homework_rules import clean_note
from app.modules.academic.domain.classwork.records import HomeworkRecord
from app.shared.actor import Actor
from app.shared.clock import Clock


class SetHomeworkNote:
    """Notes are up to 1000 characters; an empty note clears it.

    Any lesson of the student's audience takes a note, also a future one without
    homework yet: the note is the student's own and only the student sees it.
    """

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
        self, lesson_id: UUID, actor: Actor, note: str | None
    ) -> dict[str, Any]:
        """Save the note and return the updated ``HomeworkItem``."""
        clean = clean_note(note)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            lesson = await uow.lesson_reader.visible_lesson(keys_of(student), lesson_id)
            if lesson is None:
                raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})
            todo = await uow.todos.upsert_note(student.user_id, lesson_id, clean, now)
            submission = await uow.submissions.get(student.user_id, lesson_id)
            await uow.commit()
        locale = await self.people.locale(actor.user_id)
        record = HomeworkRecord(lesson, todo, submission)
        built = await self.items.build_many([record], locale)
        return built[0]
