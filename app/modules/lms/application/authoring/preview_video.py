"""Use case: a short-lived URL to stream an uploaded video of a step draft."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import VideoStreamView
from app.modules.lms.domain.authoring.errors import (
    StepNotFoundError,
    VideoBlockNotFoundError,
)
from app.modules.lms.domain.authoring.permissions import VIEW_DRAFTS
from app.modules.lms.domain.step_content import (
    InteractiveVideoBlock,
    StepContent,
    VideoBlock,
)
from app.shared.actor import Actor
from app.shared.contracts.files import FilesApi

VIDEO_URL_SECONDS = 900


class PreviewVideo:
    """Stream URL of a draft's video for the editor and the preview."""

    def __init__(self, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the unit of work factory and the files API."""
        self.uow_factory = uow_factory
        self.files = files

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> VideoStreamView:
        """Return the URL; needs `view_drafts` like the draft preview."""
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            if step.course_id != course_id:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            access = await access_to(uow, actor, course_id)
            access.require(VIEW_DRAFTS)
        content = StepContent.model_validate(step.draft)
        file_id = next(
            (
                block.file_id
                for block in content.blocks
                if isinstance(block, VideoBlock | InteractiveVideoBlock)
                and block.id == block_id
                and block.source == "upload"
            ),
            None,
        )
        if not file_id:
            raise VideoBlockNotFoundError(params={"block_id": block_id})
        url = await self.files.download_url(
            UUID(file_id), inline=True, ttl_seconds=VIDEO_URL_SECONDS
        )
        return VideoStreamView(url=url, expires_in=VIDEO_URL_SECONDS)
