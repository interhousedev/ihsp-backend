"""LMS Course tool `create_section`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "courses:draft"


def register(kit: ToolKit) -> None:
    """Register `create_section`."""

    @kit.tool(SCOPE, read_only=False)
    async def create_section(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        title: Annotated[
            str, Field(min_length=1, max_length=200, description="Section title.")
        ],
    ) -> dict[str, Any]:
        """Add a new section at the end of a course draft.

        The change is a pending change marked "via MCP"; students see it only after
        a person with the publish permission publishes the course.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_commands.create_section(
            actor, course_id, title, via_mcp=True
        )
