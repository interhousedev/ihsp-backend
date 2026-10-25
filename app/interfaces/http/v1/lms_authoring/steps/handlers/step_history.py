"""GET /v1/lms/steps/{id}/history: checkpoints and published states of a step."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    RevisionItemResponse,
    respond_list,
)


async def step_history(
    step_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> list[RevisionItemResponse]:
    """Return the history of the step, newest first."""
    views = await authoring.list_step_history.execute(actor, step_id)
    return respond_list(RevisionItemResponse, views)
