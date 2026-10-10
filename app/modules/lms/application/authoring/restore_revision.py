"""Use case: put a checkpoint or published state of a step back into its draft."""

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
    RevisionNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.lms_scopes import MODULES_WRITE


class RestoreRevision:
    """Restore one revision of a step into its working copy (as a save)."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(
        self, actor: Actor, step_id: UUID, revision_id: UUID
    ) -> StepDraftView:
        """Copy the revision content into the draft; history is never rewritten."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            access = await access_to(uow, actor, step.course_id)
            access.require(EDIT)
            access.require_scope(MODULES_WRITE)
            revision = await uow.revisions.get(revision_id)
            if revision is None or revision.step_id != step_id:
                raise RevisionNotFoundError(params={"revision_id": str(revision_id)})
            if revision.content_hash == step.draft_hash:
                return await self.presenter.step_draft(step)
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
