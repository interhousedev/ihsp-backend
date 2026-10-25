"""POST /v1/lms/courses/{id}/draft/outline: apply outline operations."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    CourseDraftResponse,
    OutlineBody,
    respond,
)


async def apply_outline(
    course_id: UUID, body: OutlineBody, actor: ActorDep, authoring: AuthoringDep
) -> CourseDraftResponse:
    """Apply the operations atomically; a stale `lock_version` is a 409."""
    view = await authoring.apply_outline_ops.execute(
        actor, course_id, body.ops, lock_version=body.lock_version
    )
    return respond(CourseDraftResponse, view)
