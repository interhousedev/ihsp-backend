"""Use case: a teacher lists their open work-offs for quick marking (WO-7)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import ViewUnitOfWork
from app.modules.academic.application.classwork.work_off_items import names_of


class ListTeacherWorkOffs:
    """Open work-offs the teacher assigned or whose lesson they teach."""

    def __init__(
        self, uow_factory: Callable[[], ViewUnitOfWork], people: PeopleDirectory
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.people = people

    async def execute(
        self, teacher_id: UUID, locale: str | None = None
    ) -> list[dict[str, Any]]:
        """Return dicts ``{id, student_name, group_name, lesson_id, date, ...}``."""
        locale = locale or await self.people.locale(teacher_id)
        async with self.uow_factory() as uow:
            views = await uow.work_off_reader.open_for_teacher(teacher_id)
        students = await names_of(self.people, (v.work_off.student_id for v in views))
        return [
            {
                "id": str(v.work_off.id),
                "student_name": students.get(v.work_off.student_id, "?"),
                "group_name": v.group_name,
                "lesson_id": str(v.work_off.lesson_id),
                "date": v.lesson_date.isoformat(),
                "subject_name": v.subject_name(locale),
                "text": v.work_off.text,
            }
            for v in views
        ]
