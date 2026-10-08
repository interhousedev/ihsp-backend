"""GET /v1/lms/courses/{id}/compare: compare two versions."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import VersionCompareResponse, respond


async def compare_versions(
    course_id: UUID, a: int, b: int, actor: ActorDep, authoring: AuthoringDep
) -> VersionCompareResponse:
    """Return which steps differ between version numbers `a` and `b`."""
    view = await authoring.compare_versions.execute(actor, course_id, a, b)
    return respond(VersionCompareResponse, view)
