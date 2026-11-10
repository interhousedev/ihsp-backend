"""LMS Course tool `list_staff`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_READ

from pydantic import Field

SCOPE = COURSES_READ


def register(kit: ToolKit) -> None:
    """Register `list_staff`."""

    @kit.tool(SCOPE)
    async def list_staff(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
    ) -> dict[str, Any]:
        """List course staff (user id, login, role label, permissions)."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.list_staff(actor, course_id)
        return result if isinstance(result, dict) else {"items": result}
