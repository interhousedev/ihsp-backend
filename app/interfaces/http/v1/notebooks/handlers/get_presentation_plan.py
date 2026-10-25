"""GET /v1/notebooks/{id}/presentation-plans/{pid}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_plans import PresentationPlanResponse


async def get_presentation_plan(
    notebook_id: UUID,
    plan_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
) -> PresentationPlanResponse:
    """Return one of the caller's presentation plans (PLAN)."""
    plan = await notebooks.get_presentation_plan.execute(actor, notebook_id, plan_id)
    return PresentationPlanResponse.from_entity(plan)
