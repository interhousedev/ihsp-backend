"""Use case: the student's lesson page (WEB-9, UF-WEB-06)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.homework_items import (
    HomeworkItemBuilder,
)
from app.modules.academic.application.classwork.lesson_items import LessonItemBuilder
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.resource_items import (
    student_resource_items,
)
from app.modules.academic.application.classwork.student_context import (
    attendance_state,
    keys_of,
    mark_item,
    require_student,
)
from app.modules.academic.domain.classwork.errors import LessonNotFoundError
from app.modules.academic.domain.classwork.records import HomeworkRecord
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.links import LinksApi

ATTACH_DAYS_BACK = 7
ATTACH_DAYS_AHEAD = 14


class StudentLesson:
    """Everything about one lesson for a student of its audience."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        lesson_items: LessonItemBuilder,
        homework: HomeworkItemBuilder,
        links: LinksApi,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.lesson_items = lesson_items
        self.homework = homework
        self.links = links

    async def execute(self, lesson_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the ``StudentLesson`` JSON; not-in-audience is "not found"."""
        today = local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            lesson = await uow.lesson_reader.visible_lesson(keys_of(student), lesson_id)
            if lesson is None:
                raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})
            todo = await uow.todos.get(student.user_id, lesson_id)
            marks = await uow.results.lesson_marks(student.user_id, lesson_id)
        refs = await self.links.lesson_resources(lesson_id, include_hidden=True)
        shown = [
            ref for ref in refs if not ref.hidden or ref.author_id == actor.user_id
        ]
        homework = None
        if lesson.has_homework:
            built = await self.homework.build_many(
                [HomeworkRecord(lesson, todo)], locale
            )
            homework = built[0]
        offset = (lesson.date - today).days
        return {
            "lesson": await self.lesson_items.build(lesson, locale),
            "materials": student_resource_items(
                [ref for ref in shown if ref.role == "material"]
            ),
            "attachments": student_resource_items(
                [ref for ref in shown if ref.role == "attachment"]
            ),
            "homework": homework,
            "my_mark": [mark_item(mark, locale) for mark in marks],
            "my_attendance": attendance_state(lesson, actor.user_id),
            "can_attach": -ATTACH_DAYS_BACK <= offset <= ATTACH_DAYS_AHEAD,
        }
