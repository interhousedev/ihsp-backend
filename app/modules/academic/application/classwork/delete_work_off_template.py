"""Use case: a teacher deletes their own work-off template (WO-1)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.domain.classwork.errors import WorkOffTemplateNotFoundError
from app.shared.actor import Actor


class DeleteWorkOffTemplate:
    """Delete one of the actor's templates; given work-offs keep their text."""

    def __init__(self, uow_factory: Callable[[], AttendanceUnitOfWork]) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, template_id: UUID) -> None:
        """Delete the template.

        Raises:
            WorkOffTemplateNotFoundError: unknown, or someone else's template.
        """
        async with self.uow_factory() as uow:
            template = await uow.work_off_templates.get(template_id)
            if template is None or template.teacher_id != actor.user_id:
                raise WorkOffTemplateNotFoundError(
                    params={"template_id": str(template_id)}
                )
            await uow.work_off_templates.delete(template_id)
            await uow.commit()
