"""LMS Course tool `move_section`."""

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
    """Register `move_section`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("course_id", "position")))
    async def move_section(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        section_id: Annotated[str, Field(description="Section id from get_course.")],
        position: Annotated[int, Field(ge=0, description="New 0-based position.")],
    ) -> dict[str, Any]:
        """Move a section to another position in the course draft.

        Example: move_section(course_id, section_id, position=0) puts it first.
        Returns the draft outline.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.move_section(
            actor, course_id, section_id, position
        )
        return result if isinstance(result, dict) else {"items": result}
