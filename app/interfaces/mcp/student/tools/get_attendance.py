"""Students tool `get_attendance`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range
from app.interfaces.mcp.student.views import with_lesson_view
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "attendance:read"


def register(kit: ToolKit) -> None:
    """Register `get_attendance`."""

    @kit.tool(SCOPE)
    async def get_attendance(
        date_from: DateFromParam = None, date_to: DateToParam = None
    ) -> dict[str, Any]:
        """List the student's own absences.

        Each absence has its lesson and whether it is excused. Lessons the student
        attended are not listed.
        """
        actor = current_actor()
        check_range(date_from, date_to)
        rows = await kit.deps.classwork.absences(actor.user_id, date_from, date_to)
        return {"absences": [with_lesson_view(row) for row in rows]}
