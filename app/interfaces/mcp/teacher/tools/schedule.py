"""Teacher tools `get_today`, `get_timetable`, `get_lesson`, `find_feature`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.feature_search import QueryParam, find_feature_result
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.jsonable import to_jsonable
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import resolve_range
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "schedule:read"


def register(kit: ToolKit) -> None:
    """Register the schedule tools."""

    @kit.tool(SCOPE)
    async def get_today() -> dict[str, Any]:
        """Today for the teacher: current or next lesson, today's lessons, missed."""
        return await kit.deps.teacher_tools.today(current_actor())

    @kit.tool(SCOPE)
    async def get_timetable(
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
    ) -> dict[str, Any]:
        """List the lessons the teacher teaches (default: the next 7 days)."""
        actor = current_actor()
        start, end = resolve_range(kit.deps, date_from, date_to, default_days=7)
        rows = await kit.deps.teacher_tools.timetable(actor, start, end)
        return {"lessons": to_jsonable(rows)}

    @kit.tool(SCOPE)
    async def get_lesson(
        lesson_id: Annotated[
            UUID, Field(description="A lesson id from the timetable.")
        ],
    ) -> dict[str, Any]:
        """One lesson of the teacher: topic, roster, attendance and homework."""
        return await kit.deps.teacher_tools.lesson(current_actor(), lesson_id)

    @kit.tool(SCOPE)
    async def find_feature(query: QueryParam) -> dict[str, Any]:
        """Find the page of the platform that does what the teacher wants."""
        return find_feature_result(kit.deps, current_actor(), query)
