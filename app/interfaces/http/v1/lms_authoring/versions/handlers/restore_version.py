"""POST /v1/lms/courses/{id}/versions/{number}/restore: restore into the draft."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import CourseDraftResponse, respond


async def restore_version(
    course_id: UUID, number: int, actor: ActorDep, authoring: AuthoringDep
) -> CourseDraftResponse:
    """Copy the version into the draft; publishing it later makes a new version."""
    view = await authoring.restore_version.execute(actor, course_id, number)
    return respond(CourseDraftResponse, view)
