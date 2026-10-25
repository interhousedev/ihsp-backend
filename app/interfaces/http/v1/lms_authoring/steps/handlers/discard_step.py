"""POST /v1/lms/steps/{id}/discard: reset a step draft to its live revision."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import StepDraftResponse, respond


async def discard_step(
    step_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> StepDraftResponse:
    """Discard the pending changes of one step."""
    view = await authoring.discard_step.execute(actor, step_id)
    return respond(StepDraftResponse, view)
