"""LMS Course tool `list_pending_changes`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "courses:read"


def register(kit: ToolKit) -> None:
    """Register `list_pending_changes`."""

    @kit.tool(SCOPE)
    async def list_pending_changes(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
    ) -> dict[str, Any]:
        """List the unpublished changes of a course (added, changed, removed steps).

        Steps changed through MCP are marked via_mcp. A person with the publish
        permission publishes them; this server cannot.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_queries.pending_changes(course_id, actor)
