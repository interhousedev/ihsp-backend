"""Students tool `get_course_curriculum`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field


def register(kit: ToolKit) -> None:
    """Register `get_course_curriculum`."""

    @kit.tool("learning:read", log=LogSpec(keep=("course_id",)))
    async def get_course_curriculum(
        course_id: Annotated[UUID, Field(description="Course from list_my_courses.")],
    ) -> dict[str, Any]:
        """Return sections and steps of an enrolled course with what is completed."""
        outline = await kit.deps.files_courses_tools.course_curriculum(
            current_actor(), course_id
        )
        return mark_untrusted(
            outline,
            "title",
            "description",
            "sections[].title",
            "sections[].steps[].title",
        )
