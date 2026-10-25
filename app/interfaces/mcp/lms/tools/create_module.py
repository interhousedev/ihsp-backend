"""LMS Course tool `create_module`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE

COURSE_ID = Annotated[UUID, Field(description="Course id from list_courses.")]


def register(kit: ToolKit) -> None:
    """Register `create_module`."""

    @kit.tool(SCOPE, read_only=False)
    async def create_module(
        course_id: COURSE_ID,
        title: Annotated[
            str, Field(min_length=1, max_length=200, description="Module title.")
        ],
    ) -> dict[str, Any]:
        """Add a module (a section of the outline) at the end of a course draft."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_commands.create_section(
            actor, course_id, title, via_mcp=True
        )
