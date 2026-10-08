"""LMS Course tool `get_course`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "courses:read"


def register(kit: ToolKit) -> None:
    """Register `get_course`."""

    @kit.tool(SCOPE)
    async def get_course(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
    ) -> dict[str, Any]:
        """Show a course draft: title, sections, steps and their change badges."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_queries.course_detail(course_id, actor)
