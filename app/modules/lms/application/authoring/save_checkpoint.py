"""Use case: save a named checkpoint of a step draft (LMS-12, UF-LMS-13)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.prune_revisions import CHECKPOINTS_KEPT
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import RevisionItemView
from app.modules.lms.domain.authoring.enums import RevisionKind
from app.modules.lms.domain.authoring.errors import TitleInvalidError
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor
from app.shared.clock import Clock

LABEL_MAX_LENGTH = 120


class SaveCheckpoint:
    """Freeze the current draft of a step without publishing it."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(
        self, actor: Actor, step_id: UUID, label: str
    ) -> RevisionItemView:
        """Store the checkpoint and drop the oldest ones beyond the newest 20."""
        name = label.strip()
        if not 1 <= len(name) <= LABEL_MAX_LENGTH:
            raise TitleInvalidError(params={"max_length": LABEL_MAX_LENGTH})
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            access = await access_to(uow, actor, step.course_id)
            access.require(EDIT)
            revision = await uow.revisions.ensure(
                step_id=step.id,
                content=step.draft,
                content_hash=step.draft_hash,
                kind=RevisionKind.CHECKPOINT,
                label=name,
                file_ids=step.file_ids,
                created_by=actor.user_id,
                now=self.clock.now(),
            )
            await uow.revisions.prune_checkpoints(
                keep=CHECKPOINTS_KEPT, step_id=step.id, protect=[revision.id]
            )
            await uow.commit()
        return (await self.presenter.revision_items([revision]))[0]
