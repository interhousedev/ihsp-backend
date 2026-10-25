"""LMS Course tool `update_module`."""

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
    """Register `update_module`."""

    @kit.tool(SCOPE, read_only=False)
    async def update_module(
        course_id: COURSE_ID,
        module_id: Annotated[
            str, Field(min_length=1, description="Module id from get_course.")
        ],
        title: Annotated[
            str, Field(min_length=1, max_length=200, description="New title.")
        ],
    ) -> dict[str, Any]:
        """Rename a module of a course draft."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_commands.update_module(
            actor, course_id, module_id, title
        )
