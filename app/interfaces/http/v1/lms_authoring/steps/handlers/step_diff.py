"""GET /v1/lms/steps/{id}/diff: live content next to draft content."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import StepDiffResponse, respond


async def step_diff(
    step_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> StepDiffResponse:
    """Return `{live, draft}`; `live` is null for a step never published."""
    view = await authoring.get_step_diff.execute(actor, step_id)
    return respond(StepDiffResponse, view)
