"""POST /v1/lms/steps/{id}/restore: put a revision back into the step draft."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    RestoreRevisionBody,
    StepDraftResponse,
    respond,
)


async def restore_revision(
    step_id: UUID,
    body: RestoreRevisionBody,
    actor: ActorDep,
    authoring: AuthoringDep,
) -> StepDraftResponse:
    """Restore a checkpoint or published state into the draft."""
    view = await authoring.restore_revision.execute(actor, step_id, body.revision_id)
    return respond(StepDraftResponse, view)
