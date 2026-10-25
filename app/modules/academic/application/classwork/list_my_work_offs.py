"""Use case: a student lists their own work-off tasks (WO-6)."""

from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import ViewUnitOfWork
from app.modules.academic.application.classwork.work_off_items import my_item, names_of


class ListMyWorkOffs:
    """The student's work-offs, newest lesson first."""

    def __init__(
        self, uow_factory: Callable[[], ViewUnitOfWork], people: PeopleDirectory
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.people = people

    async def execute(
        self,
        student_id: UUID,
        locale: str | None = None,
        status: Literal["open", "all"] = "open",
    ) -> list[dict[str, Any]]:
        """Return ``MyWorkOffResponse`` dicts of this student only."""
        locale = locale or await self.people.locale(student_id)
        async with self.uow_factory() as uow:
            views = await uow.work_off_reader.for_student(student_id, status == "open")
        teachers = await names_of(self.people, (v.lesson_teacher_id for v in views))
        return [my_item(view, locale, teachers) for view in views]
