"""JSON shapes of work-off lists shared by the student, teacher and admin views."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.domain.classwork.work_off_views import WorkOffView
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError


def ensure_admin(actor: Actor) -> None:
    """Allow Administration only.

    Raises:
        ForbiddenError: the actor is not an administrator.
    """
    if not actor.has(Role.ADMIN):
        raise ForbiddenError()


async def names_of(
    people: PeopleDirectory, ids: Iterable[UUID | None]
) -> dict[UUID, str]:
    """Display names ("First Last") of the people that exist."""
    found = await people.people(i for i in ids if i is not None)
    return {uid: f"{p.first_name} {p.last_name}" for uid, p in found.items()}


def my_item(
    view: WorkOffView, locale: str, teachers: dict[UUID, str]
) -> dict[str, Any]:
    """The ``MyWorkOffResponse`` of a student's work-off."""
    work_off = view.work_off
    teacher_id = view.lesson_teacher_id
    return {
        "id": str(work_off.id),
        "lesson_id": str(work_off.lesson_id),
        "date": view.lesson_date.isoformat(),
        "period": view.period,
        "subject_name": view.subject_name(locale),
        "teacher_name": None if teacher_id is None else teachers.get(teacher_id),
        "text": work_off.text,
        "status": work_off.status,
        "due_date": (
            None if work_off.due_date is None else work_off.due_date.isoformat()
        ),
        "done_at": None if work_off.done_at is None else work_off.done_at.isoformat(),
        "created_at": work_off.created_at.isoformat(),
    }
