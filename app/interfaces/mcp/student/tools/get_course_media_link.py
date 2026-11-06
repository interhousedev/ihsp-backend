"""Students tool `get_course_media_link`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import MEDIA_LINK_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted, safe_external_url

from pydantic import Field


def register(kit: ToolKit) -> None:
    """Register `get_course_media_link`."""

    @kit.tool(
        "learning:read",
        idempotent=False,  # each call rotates the grant and kills the previous link
        limit=MEDIA_LINK_LIMIT,
        log=LogSpec(
            keep=("course_id", "step_id"),
            summarize=lambda r: {"kind": r.get("kind")},
        ),
    )
    async def get_course_media_link(
        course_id: Annotated[UUID, Field(description="Course from list_my_courses.")],
        step_id: Annotated[UUID, Field(description="Step from the curriculum.")],
        block_id: Annotated[
            str, Field(min_length=1, max_length=100, description="Block of the step.")
        ],
    ) -> dict[str, Any]:
        """Return a link to a video or other media of an enrolled course.

        Uploaded media: `links.media` is a personal link. Anyone holding it can open it
        for 5 hours without signing in; an enrolled student signed in can always open
        it; someone signed in who is not enrolled cannot. Asking again replaces the
        previous link. Share it only if the user asks. A video from elsewhere comes as
        `external_url`, from the course content.
        """
        media = await kit.deps.files_courses_tools.issue_media_link(
            current_actor(), course_id, step_id, block_id
        )
        if "external_url" in media:
            media = {**media, "external_url": safe_external_url(media["external_url"])}
            return mark_untrusted(media, "external_url")
        return media
