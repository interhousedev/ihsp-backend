"""Students tool `list_my_courses`."""

from typing import Any

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted


def register(kit: ToolKit) -> None:
    """Register `list_my_courses`."""

    @kit.tool(
        "learning:read",
        log=LogSpec(summarize=lambda r: {"count": len(r.get("courses", []))}),
    )
    async def list_my_courses() -> dict[str, Any]:
        """List the LMS courses the student is enrolled in."""
        courses = await kit.deps.files_courses_tools.list_my_courses(current_actor())
        return mark_untrusted(
            {"courses": courses}, "courses[].title", "courses[].summary"
        )
