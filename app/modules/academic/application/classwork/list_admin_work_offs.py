"""Use case: Administration lists work-offs school-wide (WO-8)."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import ViewUnitOfWork
from app.modules.academic.application.classwork.work_off_items import (
    ensure_admin,
    names_of,
)
from app.modules.academic.domain.classwork.work_off_views import (
    StatusFilter,
    WorkOffFilter,
)
from app.shared.actor import Actor

MAX_LIMIT = 200


class ListAdminWorkOffs:
    """A filtered, paged list for the administration page."""

    def __init__(
        self, uow_factory: Callable[[], ViewUnitOfWork], people: PeopleDirectory
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.people = people

    async def execute(
        self,
        actor: Actor,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
        subject_id: UUID | None = None,
        teacher_id: UUID | None = None,
        group_id: UUID | None = None,
        student_id: UUID | None = None,
        status: StatusFilter = "all",
        limit: int = 50,
        offset: int = 0,
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Return ``{"total": int, "items": [AdminWorkOff dicts]}``.

        Raises:
            ForbiddenError: the actor is not an administrator.
        """
        ensure_admin(actor)
        locale = locale or await self.people.locale(actor.user_id)
        flt = WorkOffFilter(
            start, end, subject_id, teacher_id, group_id, student_id, status
        )
        async with self.uow_factory() as uow:
            total, views = await uow.work_off_reader.admin_list(
                flt, max(1, min(limit, MAX_LIMIT)), max(0, offset)
            )
        ids = [v.work_off.student_id for v in views]
        names = await names_of(
            self.people, [*ids, *(v.lesson_teacher_id for v in views)]
        )
        items = []
        for v in views:
            w = v.work_off
            teacher = v.lesson_teacher_id
            items.append(
                {
                    "id": str(w.id),
                    "lesson_id": str(w.lesson_id),
                    "date": v.lesson_date.isoformat(),
                    "period": v.period,
                    "subject_name": v.subject_name(locale),
                    "teacher_name": None if teacher is None else names.get(teacher),
                    "group_name": v.group_name,
                    "student_id": str(w.student_id),
                    "student_name": names.get(w.student_id, "?"),
                    "text": w.text,
                    "status": w.status,
                    "due_date": None if w.due_date is None else w.due_date.isoformat(),
                    "done_at": None if w.done_at is None else w.done_at.isoformat(),
                    "created_at": w.created_at.isoformat(),
                }
            )
        return {"total": total, "items": items}
