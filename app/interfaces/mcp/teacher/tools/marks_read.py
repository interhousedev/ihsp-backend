"""Teacher tools `list_temporary_marks` and `get_student_record`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import SemesterParam
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "marks:read"


def register(kit: ToolKit) -> None:
    """Register the marks reading tools."""

    @kit.tool(SCOPE)
    async def list_temporary_marks(
        lesson_id: Annotated[
            UUID | None,
            Field(description="One lesson; omit for all pending marks of the teacher."),
        ] = None,
    ) -> dict[str, Any]:
        """Temporary marks the teacher gave (not yet in EMIS)."""
        rows = await kit.deps.teacher_tools.temporary_marks(current_actor(), lesson_id)
        return {"marks": rows}

    @kit.tool(SCOPE)
    async def get_student_record(
        group_id: Annotated[UUID, Field(description="A group the teacher curates.")],
        semester: SemesterParam = None,
    ) -> dict[str, Any]:
        """Semester marks and attendance of every student of a curated group."""
        return await kit.deps.teacher_tools.student_record(
            current_actor(), group_id, semester
        )
