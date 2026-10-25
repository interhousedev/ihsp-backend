"""POST /v1/lms/steps/{id}/checkpoints: save a named checkpoint."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    CheckpointBody,
    RevisionItemResponse,
    respond,
)


async def save_checkpoint(
    step_id: UUID, body: CheckpointBody, actor: ActorDep, authoring: AuthoringDep
) -> RevisionItemResponse:
    """Freeze the current draft of the step under a name."""
    view = await authoring.save_checkpoint.execute(actor, step_id, body.label)
    return respond(RevisionItemResponse, view)
