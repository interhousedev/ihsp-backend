"""Students tool `get_teacher_timetable`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import resolve_range
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "teachers:read"


def register(kit: ToolKit) -> None:
    """Register `get_teacher_timetable`."""

    @kit.tool(SCOPE, log=LogSpec(keep=("teacher_id", "date_from", "date_to")))
    async def get_teacher_timetable(
        teacher_id: Annotated[
            UUID, Field(description="Teacher id from get_my_teachers.")
        ],
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
    ) -> dict[str, Any]:
        """List the lessons of one of the student's teachers (default: 7 days).

        Covers all the teacher's groups, to find when they are free; `mine` marks the
        student's own lessons. A teacher who does not teach the student is not found.
        """
        actor = current_actor()
        start, end = resolve_range(kit.deps, date_from, date_to, default_days=7)
        lessons = await kit.deps.academic_tools.teacher_timetable(
            actor, teacher_id, start, end
        )
        return {
            "date_from": start,
            "date_to": end,
            "lessons": lessons,
            "links": kit.deps.web_links.teacher(teacher_id),
        }
