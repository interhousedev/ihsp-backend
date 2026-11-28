"""Students tools `get_homework` and `get_homework_submission`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range
from app.interfaces.mcp.student.views import with_lesson_view
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "homework:read"


def register(kit: ToolKit) -> None:
    """Register the homework read tools."""

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

    @kit.tool(SCOPE)
    async def get_homework_submission(
        lesson_id: Annotated[UUID, Field(description="The lesson with the homework.")],
    ) -> dict[str, Any]:
        """The student's own submission: text, files, grade and teacher comment."""
        row = await kit.deps.academic_tools.homework_submission(
            current_actor(), lesson_id
        )
        return mark_untrusted(
            row, "text", "comment", "teacher_comment", "previous_comment"
        )
