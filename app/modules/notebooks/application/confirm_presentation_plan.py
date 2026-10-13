"""Use case: "Generate" — make the deck of a confirmed presentation plan (PLAN).

The plan is marked confirmed first (a second click gets `PlanConfirmedError`), then
the slide deck is requested like any Studio output, with the outline in its options;
when the request is refused (limits, quota) the plan becomes a draft again.
"""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.presentation_plan_access import load_own_plan
from app.modules.notebooks.application.request_artifact import RequestArtifact
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    PlanConfirmedError,
    PlanTooLongError,
)
from app.modules.notebooks.domain.presentation_plan import (
    PLAN_MAX_SLIDES,
    PLAN_MIN_SLIDES,
    PlanStatus,
    PresentationPlan,
    length_for,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.agent_steps import StepKind, record_step
from app.shared.clock import Clock


def _require_ready(plan: PresentationPlan) -> None:
    """A draft with 3 to `PLAN_MAX_SLIDES` slides.

    Raises:
        PlanConfirmedError: The deck is already generated.
        PlanTooLongError: Too many slides (the numbers are in the params).
        InvalidOptionsError: Fewer than three slides.
    """
    if plan.status is not PlanStatus.DRAFT:
        raise PlanConfirmedError()
    if plan.over_limit:
        raise PlanTooLongError(
            params={"count": len(plan.slides), "max": PLAN_MAX_SLIDES}
        )
    if len(plan.slides) < PLAN_MIN_SLIDES:
        raise InvalidOptionsError(
            params={"details": [f"slides: at least {PLAN_MIN_SLIDES}"]}
        )


class ConfirmPresentationPlan:
    """Confirms a draft plan and queues its slide deck."""

    def __init__(
        self, *, uow_factory: UowFactory, request: RequestArtifact, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.request = request
        self.clock = clock

    async def execute(
        self, actor: Actor, notebook_id: UUID, plan_id: UUID
    ) -> tuple[PresentationPlan, Artifact]:
        """Return the confirmed plan and the queued (or cached) deck.

        Raises:
            NotebookNotFoundError: No such plan of the caller in this notebook.
            PlanConfirmedError, PlanTooLongError, InvalidOptionsError: See above.
            And every refusal of `RequestArtifact` (limits, quota, busy).
        """
        plan = await self._mark(actor, notebook_id, plan_id, PlanStatus.CONFIRMED)
        options: dict[str, Any] = {
            "format": plan.format,
            "length": length_for(len(plan.slides)),
            "outline": [slide.model_dump(mode="json") for slide in plan.slides],
        }
        if plan.source_ids:
            options["source_ids"] = [str(source_id) for source_id in plan.source_ids]
        try:
            artifact = await self.request.execute(
                actor, notebook_id, ArtifactKind.SLIDES, options, plan.prompt
            )
        except BaseException:
            await self._mark(actor, notebook_id, plan_id, PlanStatus.DRAFT)
            raise
        plan = await self._link(actor, notebook_id, plan_id, artifact)
        record_step(
            StepKind.CREATE,
            "Generating slides",
            target=plan.title,
            ref=str(artifact.id),
        )
        return plan, artifact

    async def _mark(
        self, actor: Actor, notebook_id: UUID, plan_id: UUID, status: PlanStatus
    ) -> PresentationPlan:
        async with self.uow_factory() as uow:
            plan = await load_own_plan(
                uow, actor.user_id, notebook_id, plan_id, for_update=True
            )
            if status is PlanStatus.CONFIRMED:
                _require_ready(plan)
            plan.status = status
            plan.updated_at = self.clock.now()
            await uow.plans.save(plan)
            await uow.commit()
        return plan

    async def _link(
        self, actor: Actor, notebook_id: UUID, plan_id: UUID, artifact: Artifact
    ) -> PresentationPlan:
        async with self.uow_factory() as uow:
            plan = await load_own_plan(
                uow, actor.user_id, notebook_id, plan_id, for_update=True
            )
            plan.artifact_id = artifact.id
            await uow.plans.save(plan)
            await uow.commit()
        return plan
