"""Use case: a teacher adds a work-off template (WO-1)."""

from collections.abc import Callable

from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.domain.classwork.work_off import (
    WorkOffTemplate,
    clean_template_text,
    defaults_to_clear,
    ensure_template_capacity,
)
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateWorkOffTemplate:
    """Add a template; making it the default clears the previous default."""

    def __init__(
        self, uow_factory: Callable[[], AttendanceUnitOfWork], clock: Clock
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, actor: Actor, text: str, is_default: bool = False
    ) -> WorkOffTemplate:
        """Create the template for the actor.

        Raises:
            WorkOffTextInvalidError: empty or longer than 1000 characters.
            WorkOffTemplateLimitError: the teacher already has 20 templates.
        """
        cleaned = clean_template_text(text)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            existing = await uow.work_off_templates.list_for_teacher(actor.user_id)
            ensure_template_capacity(len(existing))
            template = WorkOffTemplate(
                new_id(), actor.user_id, cleaned, is_default, now, now
            )
            await uow.work_off_templates.clear_defaults(
                defaults_to_clear(existing, None, is_default), now
            )
            await uow.work_off_templates.add(template)
            await uow.commit()
        return template
