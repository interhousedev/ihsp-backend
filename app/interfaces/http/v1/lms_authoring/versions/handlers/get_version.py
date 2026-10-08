"""GET /v1/lms/courses/{id}/versions/{number}: open a version read-only."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import VersionResponse, respond


async def get_version(
    course_id: UUID, number: int, actor: ActorDep, authoring: AuthoringDep
) -> VersionResponse:
    """Return the version with its title, description and outline."""
    view = await authoring.get_version.execute(actor, course_id, number)
    return respond(VersionResponse, view)
