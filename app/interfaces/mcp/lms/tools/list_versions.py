"""LMS Course tool `list_versions`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "courses:read"


def register(kit: ToolKit) -> None:
    """Register `list_versions`."""

    @kit.tool(SCOPE)
    async def list_versions(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
    ) -> dict[str, Any]:
        """List the published versions of a course with who published them and when."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        versions = await kit.deps.lms_queries.versions(course_id, actor)
        return {"versions": versions}
