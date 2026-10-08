"""Use case: discard the pending changes of one step (LMS-10, UF-LMS-12)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.draft_writer import (
    PreparedContent,
    StepDraftWriter,
)
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import StepDraftView
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import (
    NoLiveVersionError,
    RevisionNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor
from app.shared.clock import Clock


class DiscardStep:
    """Reset a step's draft to its live revision."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(self, actor: Actor, step_id: UUID) -> StepDraftView:
        """Copy the live revision into the draft; a never-published step has none."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            access = await access_to(uow, actor, step.course_id)
            access.require(EDIT)
            if step.live_revision_id is None:
                raise NoLiveVersionError(params={"step_id": str(step_id)})
            if step.draft_hash == step.live_hash:
                return await self.presenter.step_draft(step)
            revision = await uow.revisions.get(step.live_revision_id)
            if revision is None:
                raise RevisionNotFoundError(
                    params={"revision_id": str(step.live_revision_id)}
                )
            await uow.courses.touch_draft(step.course_id, by=actor.user_id, now=now)
            locked = await uow.steps.get_locked(step_id)
            if locked is None:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            StepDraftWriter.apply(
                locked,
                PreparedContent.from_revision(revision),
                by=actor.user_id,
                via=StepVia.UI,
                now=now,
            )
            await uow.steps.save_draft(locked)
            await uow.commit()
        return await self.presenter.step_draft(locked)
