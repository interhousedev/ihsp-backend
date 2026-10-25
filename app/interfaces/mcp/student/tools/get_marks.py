"""Students tool `get_marks`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "marks:read"


def register(kit: ToolKit) -> None:
    """Register `get_marks`."""

    @kit.tool(SCOPE)
    async def get_marks(
        subject_id: Annotated[
            UUID | None, Field(description="Only marks of this subject.")
        ] = None,
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
    ) -> dict[str, Any]:
        """List the student's own marks (lesson, midterm and final) with dates."""
        actor = current_actor()
        check_range(date_from, date_to)
        marks = await kit.deps.marks.marks(
            actor.user_id, subject_id, date_from, date_to
        )
        return {"marks": marks}
