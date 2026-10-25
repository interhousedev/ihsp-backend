"""PUT /v1/lms/courses/{id}/draft/meta: save the draft title and description."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    CourseDraftResponse,
    UpdateMetaBody,
    respond,
)


async def update_meta(
    course_id: UUID, body: UpdateMetaBody, actor: ActorDep, authoring: AuthoringDep
) -> CourseDraftResponse:
    """Save the meta; a stale `lock_version` is a 409 with `params.theirs`."""
    view = await authoring.update_course_meta.execute(
        actor,
        course_id,
        title=body.title,
        description=body.description,
        lock_version=body.lock_version,
    )
    return respond(CourseDraftResponse, view)
