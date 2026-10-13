"""POST /v1/notebooks/{id}/presentation-plans."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_plans import (
    PlanCreateBody,
    PresentationPlanResponse,
)


async def create_presentation_plan(
    notebook_id: UUID,
    body: PlanCreateBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> PresentationPlanResponse:
    """Outline a slide deck; the deck is made only after "Generate" (PLAN)."""
    plan = await notebooks.create_presentation_plan.execute(
        actor,
        notebook_id,
        prompt=body.prompt,
        source_ids=body.source_ids,
        slide_count=body.slide_count,
        slide_format=body.format,
    )
    return PresentationPlanResponse.from_entity(plan)
