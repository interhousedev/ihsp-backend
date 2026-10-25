"""LMS Course tool `delete_step`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE

COURSE_ID = Annotated[UUID, Field(description="Course id from list_courses.")]


def register(kit: ToolKit) -> None:
    """Register `delete_step`."""

    @kit.tool(SCOPE, read_only=False, destructive=True)
    async def delete_step(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
    ) -> dict[str, Any]:
        """Take a step out of the course draft outline (its history is kept)."""
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        return await kit.deps.lms_commands.delete_step(actor, step_id)
