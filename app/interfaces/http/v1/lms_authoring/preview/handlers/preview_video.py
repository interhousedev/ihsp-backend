"""GET /v1/lms/courses/{id}/preview/steps/{step_id}/blocks/{block_id}/video."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import VideoStreamResponse, respond

from fastapi import Response


async def preview_video(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: ActorDep,
    authoring: AuthoringDep,
) -> VideoStreamResponse:
    """Return a stream URL of the draft's uploaded video (needs `view_drafts`)."""
    response.headers["Cache-Control"] = "no-store"
    view = await authoring.preview_video.execute(actor, course_id, step_id, block_id)
    return respond(VideoStreamResponse, view)
