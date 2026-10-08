"""Use case: list the checkpoints and published states of a step (LMS-12)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import RevisionItemView
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor

HISTORY_LIMIT = 200


class ListStepHistory:
    """Return the history of a step, newest first."""

    def __init__(self, uow_factory: UowFactory, presenter: Presenter) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(self, actor: Actor, step_id: UUID) -> list[RevisionItemView]:
        """Return publish and checkpoint revisions of the step."""
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            access = await access_to(uow, actor, step.course_id)
            access.require(EDIT)
            revisions = await uow.revisions.list_for_history(step_id, HISTORY_LIMIT)
        return await self.presenter.revision_items(revisions)
