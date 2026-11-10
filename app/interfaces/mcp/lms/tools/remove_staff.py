"""LMS Course tool `remove_staff`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_WRITE

from pydantic import Field

SCOPE = COURSES_WRITE


def register(kit: ToolKit) -> None:
    """Register `remove_staff`."""

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        log=LogSpec(keep=("course_id", "user_id")),
    )
    async def remove_staff(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        user_id: Annotated[UUID, Field(description="User id from list_staff.")],
    ) -> dict[str, Any]:
        """Remove a member from the course staff."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.remove_staff(actor, course_id, user_id)
        return result if isinstance(result, dict) else {"items": result}
