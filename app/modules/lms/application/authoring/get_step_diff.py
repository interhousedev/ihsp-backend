"""Use case: show the live content of a step next to its draft (UF-LMS-10)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import StepDiffView
from app.modules.lms.domain.authoring.errors import RevisionNotFoundError
from app.modules.lms.domain.authoring.permissions import EDIT, PUBLISH
from app.modules.lms.domain.step_content import StepContent
from app.shared.actor import Actor


class GetStepDiff:
    """Return both sides of a step diff; the client computes the visual diff."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, step_id: UUID) -> StepDiffView:
        """Return the live content (None for a new step) and the draft content."""
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            access = await access_to(uow, actor, step.course_id)
            access.require(EDIT, PUBLISH)
            live: StepContent | None = None
            if step.live_revision_id is not None:
                revision = await uow.revisions.get(step.live_revision_id)
                if revision is None:
                    raise RevisionNotFoundError(
                        params={"revision_id": str(step.live_revision_id)}
                    )
                live = StepContent.model_validate(revision.content)
        return StepDiffView(live=live, draft=StepContent.model_validate(step.draft))
