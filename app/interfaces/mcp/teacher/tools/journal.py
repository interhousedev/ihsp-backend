"""Teacher tools `get_journal`, `get_group_attendance`, `my_missing_attendance`."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.jsonable import to_jsonable
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range, resolve_range
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "journal:read"


def register(kit: ToolKit) -> None:
    """Register the journal and attendance tools."""

    @kit.tool(SCOPE)
    async def get_journal(
        subject_id: Annotated[UUID, Field(description="The subject of the journal.")],
        audience_key: Annotated[
            str, Field(description="The audience key from `list_my_groups`.")
        ],
        term_id: Annotated[
            UUID | None, Field(description="A term; the current one if omitted.")
        ] = None,
    ) -> dict[str, Any]:
        """Students by lessons of a journal the teacher teaches."""
        return await kit.deps.teacher_tools.journal(
            current_actor(), subject_id, audience_key, term_id
        )

    @kit.tool(SCOPE)
    async def get_group_attendance(
        group_id: Annotated[UUID, Field(description="A group the teacher curates.")],
        view: Annotated[
            Literal["student", "subject", "day", "lesson"],
            Field(description="How to group the report."),
        ] = "student",
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
    ) -> dict[str, Any]:
        """The attendance report of a curated group."""
        actor = current_actor()
        check_range(date_from, date_to)
        return await kit.deps.teacher_tools.group_attendance(
            actor, group_id, view, date_from, date_to
        )

    @kit.tool(SCOPE)
    async def my_missing_attendance(
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
    ) -> dict[str, Any]:
        """The teacher's own finished lessons without an attendance list."""
        actor = current_actor()
        start, end = resolve_range(kit.deps, date_from, date_to, default_days=7)
        rows = await kit.deps.teacher_tools.missing_attendance(actor, start, end)
        return {"lessons": to_jsonable(rows)}
