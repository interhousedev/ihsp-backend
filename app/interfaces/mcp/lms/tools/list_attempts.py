"""LMS Course tool `list_attempts`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_READ

from pydantic import Field

SCOPE = COURSES_READ


def register(kit: ToolKit) -> None:
    """Register `list_attempts`."""

    @kit.tool(SCOPE)
    async def list_attempts(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        limit: Annotated[int, Field(ge=1, le=100, description="Most attempts.")] = 50,
    ) -> dict[str, Any]:
        """List the most recent test attempts of a course (student, score, result)."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        attempts = await kit.deps.lms_queries.attempts(course_id, actor, limit)
        return {"attempts": attempts}
