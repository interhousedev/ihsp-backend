"""GET /v1/lms/courses/{id}/pending: the pending changes of a course."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import PendingChangesResponse, respond


async def pending_changes(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> PendingChangesResponse:
    """Return added, changed and removed steps and `draft_seq` for publishing."""
    view = await authoring.get_pending_changes.execute(actor, course_id)
    return respond(PendingChangesResponse, view)
