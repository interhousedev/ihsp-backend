"""GET /v1/lms/steps/{id}/draft: open the draft of a step."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import StepDraftResponse, respond


async def get_step_draft(
    step_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> StepDraftResponse:
    """Return the working copy of the step."""
    view = await authoring.get_step_draft.execute(actor, step_id)
    return respond(StepDraftResponse, view)
