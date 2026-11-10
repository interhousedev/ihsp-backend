"""LMS Course tool `get_settings`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_READ

from pydantic import Field

SCOPE = COURSES_READ


def register(kit: ToolKit) -> None:
    """Register `get_settings`."""

    @kit.tool(SCOPE)
    async def get_settings(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
    ) -> dict[str, Any]:
        """Read course settings: visibility, cover and invite data."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.settings(actor, course_id)
        return result if isinstance(result, dict) else {"items": result}
