"""Use case: a teacher lists their own work-off templates (WO-1)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.domain.classwork.work_off import WorkOffTemplate


class ListWorkOffTemplates:
    """Return the teacher's templates, oldest first."""

    def __init__(self, uow_factory: Callable[[], AttendanceUnitOfWork]) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, teacher_id: UUID) -> list[WorkOffTemplate]:
        """Return the templates owned by ``teacher_id``."""
        async with self.uow_factory() as uow:
            return await uow.work_off_templates.list_for_teacher(teacher_id)
