"""LMS Course tool `update_course`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_WRITE

from pydantic import Field

SCOPE = COURSES_WRITE

COURSE_ID = Annotated[UUID, Field(description="Course id from list_courses.")]


def register(kit: ToolKit) -> None:
    """Register `update_course`."""

    @kit.tool(SCOPE, read_only=False)
    async def update_course(
        course_id: COURSE_ID,
        title: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=200, description="New title."),
        ] = None,
        description: Annotated[
            str | None,
            Field(default=None, max_length=5000, description="New description."),
        ] = None,
    ) -> dict[str, Any]:
        """Change the title and/or description of a course draft (not published)."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_commands.update_course(
            actor, course_id, title=title, description=description
        )
