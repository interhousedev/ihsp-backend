"""POST /v1/lms/courses/{id}/discard: reset the draft to the live version."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import CourseDraftResponse, respond


async def discard_course(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> CourseDraftResponse:
    """Discard every pending change of the course."""
    view = await authoring.discard_course.execute(actor, course_id)
    return respond(CourseDraftResponse, view)
