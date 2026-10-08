"""GET /v1/lms/courses/{id}/versions: the published versions."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    VersionItemResponse,
    respond_list,
)


async def list_versions(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> list[VersionItemResponse]:
    """Return every version of the course, newest first."""
    views = await authoring.list_versions.execute(actor, course_id)
    return respond_list(VersionItemResponse, views)
