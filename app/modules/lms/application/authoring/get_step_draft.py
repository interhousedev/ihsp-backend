"""Use case: open the draft of one step (LMS-6)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import StepDraftView
from app.modules.lms.domain.authoring.permissions import EDIT, VIEW_DRAFTS
from app.shared.actor import Actor


class GetStepDraft:
    """Return the working copy of a step."""

    def __init__(self, uow_factory: UowFactory, presenter: Presenter) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(self, actor: Actor, step_id: UUID) -> StepDraftView:
        """Return `StepDraft` for staff with `edit` or `view_drafts`."""
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            access = await access_to(uow, actor, step.course_id)
            access.require(EDIT, VIEW_DRAFTS)
            access.require_read_scope()
        return await self.presenter.step_draft(step)
