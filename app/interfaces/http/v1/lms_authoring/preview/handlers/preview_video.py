"""GET /v1/lms/courses/{id}/preview/steps/{step_id}/blocks/{block_id}/video|captions."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import VideoStreamResponse, respond
from app.modules.lms.application.learning.views import VideoCaptionsView

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


async def preview_video_captions(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: ActorDep,
    authoring: AuthoringDep,
) -> VideoCaptionsView:
    """Return caption track URLs of the draft's video (needs `view_drafts`)."""
    response.headers["Cache-Control"] = "no-store"
    return await authoring.preview_video_captions.execute(
        actor, course_id, step_id, block_id
    )
