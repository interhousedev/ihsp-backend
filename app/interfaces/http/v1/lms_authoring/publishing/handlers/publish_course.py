"""POST /v1/lms/courses/{id}/publish: publish the pending changes."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    PublishBody,
    VersionItemResponse,
    respond,
)


async def publish_course(
    course_id: UUID, body: PublishBody, actor: ActorDep, authoring: AuthoringDep
) -> VersionItemResponse:
    """Publish a new version; `409 lms/draft-changed` if the draft moved."""
    view = await authoring.publish_course.execute(
        actor, course_id, draft_seq=body.draft_seq, note=body.note
    )
    return respond(VersionItemResponse, view)
