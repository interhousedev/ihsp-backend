"""PUT /v1/lms/steps/{id}/draft: save the draft of a step."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    SaveStepDraftBody,
    StepDraftResponse,
    respond,
)


async def save_step_draft(
    step_id: UUID, body: SaveStepDraftBody, actor: ActorDep, authoring: AuthoringDep
) -> StepDraftResponse:
    """Save the content; a stale `lock_version` is a 409 with `params.theirs`."""
    view = await authoring.save_step_draft.execute(
        actor, step_id, body.content, body.lock_version
    )
    return respond(StepDraftResponse, view)
