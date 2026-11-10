"""Teacher tool `list_assessments`."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "assessments:read"


def register(kit: ToolKit) -> None:
    """Register `list_assessments`."""

    @kit.tool(SCOPE)
    async def list_assessments(
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
        subject_id: Annotated[UUID | None, Field(description="One subject.")] = None,
        group_id: Annotated[UUID | None, Field(description="One group.")] = None,
        kind: Annotated[
            Literal["midterm", "final", "other"] | None,
            Field(description="midterm: ПК, final: ИК, other: a test or quiz."),
        ] = None,
        status: Annotated[
            Literal["planned", "tentative", "cancelled"] | None,
            Field(description="Only controls in this state."),
        ] = None,
    ) -> dict[str, Any]:
        """List the controls (ПК, ИК, tests) of the teacher's subjects and groups."""
        actor = current_actor()
        check_range(date_from, date_to)
        rows = await kit.deps.teacher_tools.list_assessments(
            actor,
            start=date_from,
            end=date_to,
            subject_id=subject_id,
            group_id=group_id,
            kind=kind,
            status=status,
        )
        return {"assessments": rows}
