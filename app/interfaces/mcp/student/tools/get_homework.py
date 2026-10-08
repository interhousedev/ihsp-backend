"""Students tool `get_homework`."""

from typing import Annotated, Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range
from app.interfaces.mcp.student.views import with_lesson_view
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "homework:read"


def register(kit: ToolKit) -> None:
    """Register `get_homework`."""

    @kit.tool(SCOPE)
    async def get_homework(
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
        done: Annotated[
            bool | None,
            Field(description="true: only done, false: only open, omit: all."),
        ] = None,
    ) -> dict[str, Any]:
        """List the student's homework with its done state and personal notes.

        The date range filters by the lesson date.
        """
        actor = current_actor()
        check_range(date_from, date_to)
        rows = await kit.deps.classwork.homework(
            actor.user_id, date_from, date_to, done
        )
        return {"homework": [with_lesson_view(row) for row in rows]}
