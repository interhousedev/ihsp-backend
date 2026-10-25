"""Use case: edit a draft presentation plan (PLAN).

The student renames the deck, edits slide titles and bullets, deletes and reorders
slides: the new list replaces the old one. A plan may be saved above the slide limit
(the view then offers to trim it); only "Generate" refuses it.
"""

from uuid import UUID

from app.modules.notebooks.application.presentation_plan_access import load_own_plan
from app.modules.notebooks.domain.errors import InvalidOptionsError, PlanConfirmedError
from app.modules.notebooks.domain.presentation_plan import (
    PlanSlide,
    PlanStatus,
    PresentationPlan,
    clean_slides,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock

TITLE_CHARS = 255


class UpdatePresentationPlan:
    """Replaces the title and/or the slides of a draft plan."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        plan_id: UUID,
        *,
        title: str | None,
        slides: list[PlanSlide] | None,
    ) -> PresentationPlan:
        """Return the saved plan.

        Raises:
            NotebookNotFoundError: No such plan of the caller in this notebook.
            PlanConfirmedError: The deck of the plan is already generated.
            InvalidOptionsError: The title is empty.
        """
        async with self.uow_factory() as uow:
            plan = await load_own_plan(
                uow, actor.user_id, notebook_id, plan_id, for_update=True
            )
            if plan.status is not PlanStatus.DRAFT:
                raise PlanConfirmedError()
            if title is not None:
                plan.title = _title(title)
            if slides is not None:
                plan.slides = clean_slides(slides)
            plan.updated_at = self.clock.now()
            await uow.plans.save(plan)
            await uow.commit()
        return plan


def _title(text: str) -> str:
    flat = " ".join(text.split())[:TITLE_CHARS]
    if not flat:
        raise InvalidOptionsError(params={"details": ["title: must not be empty"]})
    return flat
