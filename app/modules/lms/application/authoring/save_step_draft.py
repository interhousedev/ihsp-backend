"""Use case: save a step draft with optimistic locking (LMS-6, LMS-13, LMS-23)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.conflicts import step_conflict
from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import StepDraftView
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import StepNotFoundError
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.domain.step_content import StepContent
from app.shared.actor import Actor
from app.shared.clock import Clock


class SaveStepDraft:
    """Overwrite a step's working copy; students never see it before publishing."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        presenter: Presenter,
        writer: StepDraftWriter,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter
        self.writer = writer

    async def execute(
        self,
        actor: Actor,
        step_id: UUID,
        content: StepContent,
        lock_version: int,
        *,
        via: StepVia = StepVia.UI,
    ) -> StepDraftView:
        """Save the content; a stale `lock_version` raises a conflict with `theirs`.

        The course row is locked first (by bumping `draft_seq`) and the step row
        second, the same order as publishing, so the two never deadlock.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            access = await access_to(uow, actor, step.course_id)
            access.require(EDIT)
            prepared = await self.writer.prepare(uow, step, content)
            if prepared.content_hash == step.draft_hash:
                return await self.presenter.step_draft(step)
            await uow.courses.touch_draft(step.course_id, by=actor.user_id, now=now)
            locked = await uow.steps.get_locked(step_id)
            if locked is None:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            if locked.lock_version != lock_version:
                raise await step_conflict(self.presenter, locked)
            self.writer.apply(locked, prepared, by=actor.user_id, via=via, now=now)
            await uow.steps.save_draft(locked)
            await uow.commit()
        return await self.presenter.step_draft(locked)
