"""GET /v1/lms/courses/{id}/draft: open the course draft."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import CourseDraftResponse, respond


async def get_course_draft(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> CourseDraftResponse:
    """Return the draft outline with badges and the pending count."""
    view = await authoring.get_course_draft.execute(actor, course_id)
    return respond(CourseDraftResponse, view)
