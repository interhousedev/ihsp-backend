"""Use case: a teacher edits their own work-off template (WO-1)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.domain.classwork.errors import WorkOffTemplateNotFoundError
from app.modules.academic.domain.classwork.work_off import (
    WorkOffTemplate,
    clean_template_text,
    defaults_to_clear,
)
from app.shared.actor import Actor
from app.shared.clock import Clock


class UpdateWorkOffTemplate:
    """Change text and default flag of one of the actor's templates."""

    def __init__(
        self, uow_factory: Callable[[], AttendanceUnitOfWork], clock: Clock
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, actor: Actor, template_id: UUID, text: str, is_default: bool = False
    ) -> WorkOffTemplate:
        """Save the template.

        Raises:
            WorkOffTemplateNotFoundError: unknown, or someone else's template.
            WorkOffTextInvalidError: empty or longer than 1000 characters.
        """
        cleaned = clean_template_text(text)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            existing = await uow.work_off_templates.list_for_teacher(actor.user_id)
            if template_id not in {t.id for t in existing}:
                raise WorkOffTemplateNotFoundError(
                    params={"template_id": str(template_id)}
                )
            await uow.work_off_templates.clear_defaults(
                defaults_to_clear(existing, template_id, is_default), now
            )
            template = await uow.work_off_templates.update(
                template_id, text=cleaned, is_default=is_default, at=now
            )
            await uow.commit()
        return template
