"""Use case: freeze a step draft as a preview revision for test attempts (LMS-8)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.enums import RevisionKind
from app.modules.lms.domain.authoring.permissions import VIEW_DRAFTS
from app.shared.actor import Actor
from app.shared.clock import Clock


class EnsurePreviewRevision:
    """Give preview attempts an immutable revision to point at."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, step_id: UUID, actor: Actor) -> UUID:
        """Return the ID of a revision with the current draft content."""
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            access = await access_to(uow, actor, step.course_id)
            access.require(VIEW_DRAFTS)
            revision = await uow.revisions.ensure(
                step_id=step.id,
                content=step.draft,
                content_hash=step.draft_hash,
                kind=RevisionKind.PREVIEW,
                label=None,
                file_ids=step.file_ids,
                created_by=actor.user_id,
                now=self.clock.now(),
            )
            await uow.commit()
        return revision.id

    async def ensure_preview_revision(self, step_id: UUID, actor: Actor) -> UUID:
        """Same as execute; the name of the port B13's learning side expects."""
        return await self.execute(step_id, actor)
