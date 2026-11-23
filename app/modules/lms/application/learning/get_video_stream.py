"""Use cases: short-lived URLs of an uploaded video and its caption tracks."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import (
    load_live_step,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    CaptionUrlView,
    VideoCaptionsView,
    VideoStreamView,
)
from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    NotEnrolledError,
    VideoNotFoundError,
)
from app.modules.lms.domain.learning.live import RenderCache
from app.shared.actor import Actor
from app.shared.contracts.files import FilesApi

VIDEO_URL_SECONDS = 900  # S3 checks the signature when a request starts; ranges too


class GetVideoStream:
    """Check enrollment (or staff), then presign a GET of the video file.

    Seeking works because the presigned URL goes straight to S3, which answers
    ``Range`` requests.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        cache: RenderCache,
        files: FilesApi | None,
        gate: AudienceGate,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.cache = cache
        self.files = files
        self.gate = gate

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> VideoStreamView:
        """Return the stream URL of the uploaded video block of the live step."""
        blocks = await self.live_blocks(actor, course_id, step_id)
        file_id = next(
            (
                block.get("file_id")
                for block in blocks
                if block["id"] == block_id
                and block["type"] in ("video", "interactive_video")
                and block.get("source") == "upload"
            ),
            None,
        )
        if not file_id or self.files is None:
            raise VideoNotFoundError(params={"block_id": block_id})
        url = await self.files.download_url(
            UUID(file_id), inline=True, ttl_seconds=VIDEO_URL_SECONDS
        )
        return VideoStreamView(url=url, expires_in=VIDEO_URL_SECONDS)

    async def live_blocks(
        self, actor: Actor, course_id: UUID, step_id: UUID
    ) -> list[dict[str, Any]]:
        """Return the rendered blocks of the live step the actor may open."""
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            if context.course.id != course_id:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            enrolled = await uow.enrollments.get(course_id, actor.user_id)
            if (
                enrolled is None
                and not (await staff_access(uow, actor, course_id)).is_staff
            ):
                raise NotEnrolledError(params={"course_id": str(course_id)})
            await self.gate.require_step(uow, actor, course_id, step_id)
            rendered = await load_rendered(
                uow, self.cache, context.live_step.revision_id
            )
        return list(rendered.blocks)


class GetVideoCaptions:
    """Same checks as the stream; presign a GET of each WebVTT caption track."""

    def __init__(self, stream: GetVideoStream) -> None:
        """Reuse the stream use case for the access checks."""
        self.stream = stream

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> VideoCaptionsView:
        """Return the caption tracks of a video block of the live step."""
        blocks = await self.stream.live_blocks(actor, course_id, step_id)
        block = next(
            (b for b in blocks if b["id"] == block_id and b["type"] == "video"), None
        )
        files = self.stream.files
        if block is None or files is None:
            raise VideoNotFoundError(params={"block_id": block_id})
        return await caption_urls(files, block.get("captions") or [])


async def caption_urls(
    files: FilesApi, tracks: list[dict[str, Any]]
) -> VideoCaptionsView:
    """Presign a GET of each caption track (`lang`, `label`, `default`, `file_id`)."""
    views = [
        CaptionUrlView(
            lang=track["lang"],
            label=track["label"],
            default=bool(track.get("default")),
            url=await files.download_url(
                UUID(track["file_id"]), inline=True, ttl_seconds=VIDEO_URL_SECONDS
            ),
        )
        for track in tracks
    ]
    return VideoCaptionsView(tracks=views, expires_in=VIDEO_URL_SECONDS)
