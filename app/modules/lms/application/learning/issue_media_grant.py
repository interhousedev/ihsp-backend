"""Use case: a link to the media of a block for an enrolled student (MCP-B5)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import load_live_step
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    VideoNotFoundError,
)
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.domain.learning.media_grant import (
    ANONYMOUS_WINDOW,
    hash_token,
    new_token,
)
from app.shared.actor import Actor
from app.shared.clock import Clock

MEDIA_BLOCK_TYPES = ("video", "interactive_video")


@dataclass(frozen=True, slots=True)
class IssuedMedia:
    """A new token for an upload, or the address of a linked video."""

    token: str | None = None
    expires_at: datetime | None = None
    external_url: str | None = None


class IssueMediaGrant:
    """Rotate the one grant of (actor, step, block); not enrolled is not found."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, cache: RenderCache
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.cache = cache

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> IssuedMedia:
        """Return a token shown only now; only its hash is stored."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            enrolled = await uow.enrollments.get(course_id, actor.user_id)
            if (
                context.course.id != course_id
                or not context.course.is_open_for_students
                or enrolled is None
            ):
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            rendered = await load_rendered(
                uow, self.cache, context.live_step.revision_id
            )
            block = next(
                (
                    item
                    for item in rendered.blocks
                    if item["id"] == block_id and item["type"] in MEDIA_BLOCK_TYPES
                ),
                None,
            )
            if block is None:
                raise VideoNotFoundError(params={"block_id": block_id})
            if block.get("source") != "upload" or not block.get("file_id"):
                return IssuedMedia(external_url=block.get("url") or None)
            token = new_token()
            expires_at = now + ANONYMOUS_WINDOW
            await uow.media_grants.rotate(
                token_hash=hash_token(token),
                course_id=course_id,
                step_id=step_id,
                block_id=block_id,
                file_id=UUID(block["file_id"]),
                issued_to=actor.user_id,
                connector_id=actor.connector_id,
                expires_at=expires_at,
            )
            await uow.commit()
        return IssuedMedia(token=token, expires_at=expires_at)
