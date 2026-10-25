"""Use case: the lesson's teacher removes a work-off (WO-3)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import WorkOffNotFoundError
from app.shared.actor import Actor


class DeleteWorkOff:
    """Delete one work-off."""

    def __init__(self, uow_factory: Callable[[], AttendanceUnitOfWork]) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, work_off_id: UUID, actor: Actor) -> None:
        """Delete the work-off.

        Raises:
            WorkOffNotFoundError: no such work-off.
            NotLessonTeacherError: the actor neither teaches the lesson nor is admin.
        """
        async with self.uow_factory() as uow:
            current = await uow.work_offs.get(work_off_id)
            if current is None:
                raise WorkOffNotFoundError(params={"work_off_id": str(work_off_id)})
            ensure_lesson_staff(await require_lesson(uow, current.lesson_id), actor)
            await uow.work_offs.delete(work_off_id)
            await uow.commit()
