"""LMS Course tool `list_students`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_READ

from pydantic import Field

SCOPE = COURSES_READ


def register(kit: ToolKit) -> None:
    """Register `list_students`."""

    @kit.tool(SCOPE)
    async def list_students(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
    ) -> dict[str, Any]:
        """List enrolled students of a course with their progress."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.students(actor, course_id)
        return result if isinstance(result, dict) else {"items": result}
