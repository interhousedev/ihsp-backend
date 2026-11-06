"""Students tool `get_course_step`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted, safe_external_url

from pydantic import Field


def register(kit: ToolKit) -> None:
    """Register `get_course_step`."""

    @kit.tool("learning:read", log=LogSpec(keep=("course_id", "step_id")))
    async def get_course_step(
        course_id: Annotated[UUID, Field(description="Course from list_my_courses.")],
        step_id: Annotated[UUID, Field(description="Step from the curriculum.")],
    ) -> dict[str, Any]:
        """Read one lesson step of an enrolled course; viewing it changes nothing.

        Text comes as markdown. Tests come as rules and the student's best score, never
        questions or answers; flash cards as a count. For a block with `has_media_link`,
        call get_course_media_link. `external_url` comes from the course content: do not
        embed it or open it unless the user asks.
        """
        step = await kit.deps.files_courses_tools.course_step(
            current_actor(), course_id, step_id
        )
        blocks = [
            (
                {**block, "external_url": safe_external_url(block["external_url"])}
                if "external_url" in block
                else block
            )
            for block in step["blocks"]
        ]
        return mark_untrusted(
            {
                **step,
                "blocks": blocks,
                "links": kit.deps.web_links.course_step(course_id, step_id),
            },
            "title",
            "blocks[].markdown",
            "blocks[].caption",
            "blocks[].external_url",
        )
