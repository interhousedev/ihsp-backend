"""Teacher tools `set_temporary_mark` and `delete_temporary_mark`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "marks:write"

LessonIdParam = Annotated[
    UUID, Field(description="A lesson the teacher teaches (id from the timetable).")
]
StudentIdParam = Annotated[UUID, Field(description="A student of that lesson.")]


def register(kit: ToolKit) -> None:
    """Register the marks writing tools."""

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id", "student_id", "value")),
    )
    async def set_temporary_mark(
        lesson_id: LessonIdParam,
        student_id: StudentIdParam,
        value: Annotated[int, Field(ge=2, le=5, description="The mark: 2, 3, 4 or 5.")],
        comment: Annotated[
            str | None, Field(max_length=500, description="Optional note.")
        ] = None,
    ) -> dict[str, Any]:
        """Give or replace a student's temporary mark in a lesson of the teacher."""
        return await kit.deps.teacher_tools.set_temporary_mark(
            current_actor(), lesson_id, student_id, value, comment
        )

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id", "student_id")),
    )
    async def delete_temporary_mark(
        lesson_id: LessonIdParam, student_id: StudentIdParam
    ) -> dict[str, Any]:
        """Remove a student's temporary mark of one of the teacher's lessons."""
        await kit.deps.teacher_tools.delete_temporary_mark(
            current_actor(), lesson_id, student_id
        )
        return {"deleted": True}
