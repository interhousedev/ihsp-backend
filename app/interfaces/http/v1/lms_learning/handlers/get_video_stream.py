"""GET /v1/lms/courses/{id}/steps/{step_id}/blocks/{block_id}/video: stream URL."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.lms.application.learning.views import VideoStreamView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def get_video_stream(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> VideoStreamView:
    """Return a presigned GET URL of an uploaded video (enrolled or staff)."""
    response.headers["Cache-Control"] = "no-store"
    view: VideoStreamView = await container.lms.learning.get_video_stream.execute(
        actor, course_id, step_id, block_id
    )
    return view
