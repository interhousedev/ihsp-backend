"""Teacher tool `get_unfinished_work_report`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import resolve_range
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "workoffs:read"


def register(kit: ToolKit) -> None:
    """Register `get_unfinished_work_report`."""

    @kit.tool(SCOPE)
    async def get_unfinished_work_report(
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
    ) -> dict[str, Any]:
        """Absent or excused students of the teacher's lessons who still owe work.

        Lists them per lesson (without those who already have a work-off) and the
        teacher's open work-offs. Defaults to the last 14 days.
        """
        actor = current_actor()
        start, end = resolve_range(kit.deps, date_from, date_to, default_days=14)
        return await kit.deps.teacher_tools.unfinished_work_report(actor, start, end)
