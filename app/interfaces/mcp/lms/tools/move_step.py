"""LMS Course tool `move_step`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `move_step`."""

    @kit.tool(
        SCOPE, read_only=False, log=LogSpec(keep=("course_id", "step_id", "position"))
    )
    async def move_step(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        to_section_id: Annotated[str, Field(description="Target section id.")],
        position: Annotated[int, Field(ge=0, description="New 0-based position.")],
    ) -> dict[str, Any]:
        """Move a step to a position inside any section (same or another).

        Returns the draft outline. Use get_course to read section ids.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.move_step(
            actor, course_id, step_id, to_section_id, position
        )
        return result if isinstance(result, dict) else {"items": result}
