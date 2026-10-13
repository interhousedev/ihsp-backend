"""PATCH /v1/notebooks/{id}/presentation-plans/{pid}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_plans import (
    PlanUpdateBody,
    PresentationPlanResponse,
)


async def update_presentation_plan(
    notebook_id: UUID,
    plan_id: UUID,
    body: PlanUpdateBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> PresentationPlanResponse:
    """Save the edited outline: titles, bullets, deleted and moved slides (PLAN)."""
    slides = None if body.slides is None else [s.to_slide() for s in body.slides]
    plan = await notebooks.update_presentation_plan.execute(
        actor, notebook_id, plan_id, title=body.title, slides=slides
    )
    return PresentationPlanResponse.from_entity(plan)
