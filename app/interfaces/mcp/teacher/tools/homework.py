"""Teacher tools `set_homework` and `clear_homework`."""

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "homework:write"

LessonIdParam = Annotated[
    UUID, Field(description="A lesson the teacher teaches (id from the timetable).")
]


def register(kit: ToolKit) -> None:
    """Register the homework tools."""

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id", "due_date")),
    )
    async def set_homework(
        lesson_id: LessonIdParam,
        text: Annotated[
            str, Field(min_length=1, max_length=4000, description="The assignment.")
        ],
        due_date: Annotated[
            date | None, Field(description="Due date, YYYY-MM-DD; optional.")
        ] = None,
    ) -> dict[str, Any]:
        """Set (replace) the homework of one of the teacher's lessons."""
        return await kit.deps.teacher_tools.set_homework(
            current_actor(), lesson_id, text.strip(), due_date
        )

    @kit.tool("homework:read")
    async def list_homework_submissions(lesson_id: LessonIdParam) -> dict[str, Any]:
        """Who handed in the homework of one of the teacher's lessons.

        Every student of the group has a status (submitted, late, missing); handed-in
        files carry a time-limited `download_url`.
        """
        return await kit.deps.teacher_tools.homework_submissions(
            current_actor(), lesson_id
        )

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id",)),
    )
    async def clear_homework(lesson_id: LessonIdParam) -> dict[str, Any]:
        """Remove the homework of one of the teacher's lessons."""
        return await kit.deps.teacher_tools.clear_homework(current_actor(), lesson_id)
