"""Students tool `get_schedule`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import resolve_range
from app.interfaces.mcp.student.views import lesson_view
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "schedule:read"


def register(kit: ToolKit) -> None:
    """Register `get_schedule`."""

    @kit.tool(SCOPE)
    async def get_schedule(
        date_from: DateFromParam = None, date_to: DateToParam = None
    ) -> dict[str, Any]:
        """List the student's own lessons in a date range (default: today + 6 days).

        Each lesson has date, period, times (UTC), subject, room, status
        (scheduled or cancelled), topic and homework.
        """
        actor = current_actor()
        start, end = resolve_range(kit.deps, date_from, date_to, default_days=7)
        lessons = await kit.deps.schedule.projected_lessons_for_student(
            actor.user_id, start, end
        )
        return {
            "date_from": start,
            "date_to": end,
            "lessons": [lesson_view(lesson) for lesson in lessons],
        }
