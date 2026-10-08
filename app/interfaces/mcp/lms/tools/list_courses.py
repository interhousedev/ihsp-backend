"""LMS Course tool `list_courses`."""

from typing import Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import allowed_courses
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "courses:read"


def _is_visible(course: dict[str, Any], allowed: frozenset[UUID] | None) -> bool:
    if allowed is None:
        return True
    try:
        return UUID(str(course.get("id"))) in allowed
    except ValueError:
        return False


def register(kit: ToolKit) -> None:
    """Register `list_courses`."""

    @kit.tool(SCOPE)
    async def list_courses() -> dict[str, Any]:
        """List the courses the user can edit (and this connector may use)."""
        actor = current_actor()
        courses = await kit.deps.lms_queries.courses_for_staff(actor.user_id, "edit")
        allowed = await allowed_courses(kit, actor)
        return {"courses": [c for c in courses if _is_visible(c, allowed)]}
