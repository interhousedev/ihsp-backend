"""POST /v1/notebooks/{id}/presentation-plans/{pid}/confirm."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_plans import PlanConfirmResponse


async def confirm_presentation_plan(
    notebook_id: UUID,
    plan_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
) -> PlanConfirmResponse:
    """Generate: queue the deck of the plan (422 `plan-too-long` over the limit)."""
    plan, artifact = await notebooks.confirm_presentation_plan.execute(
        actor, notebook_id, plan_id
    )
    return PlanConfirmResponse.from_result(plan, artifact)
