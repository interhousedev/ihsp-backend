"""Small shared lookups for the classwork use cases."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.ports.unit_of_work import (
    LessonUnitOfWork,
)
from app.modules.academic.domain.classwork.errors import (
    AttendanceConflictError,
    LessonNotFoundError,
    NotCuratorError,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import ScheduleQueries


async def require_lesson(uow: LessonUnitOfWork, lesson_id: UUID) -> Lesson:
    """Return the lesson or raise LessonNotFoundError."""
    lesson = await uow.lessons.get(lesson_id)
    if lesson is None:
        raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})
    return lesson


def conflict_with(sheet: dict[str, Any]) -> AttendanceConflictError:
    """Build the 409 that carries the current sheet for the user to review."""
    return AttendanceConflictError(
        params={"current": sheet, "theirs": sheet, "version": sheet["version"]}
    )


async def ensure_curator(
    schedule: ScheduleQueries, actor: Actor, group_id: UUID
) -> None:
    """Allow Administration and the group's curator, refuse everyone else."""
    if actor.has(Role.ADMIN):
        return
    if group_id not in await schedule.curated_group_ids(actor.user_id):
        raise NotCuratorError(params={"group_id": str(group_id)})
