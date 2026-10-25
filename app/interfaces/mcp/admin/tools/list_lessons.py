"""Administration tool `list_lessons`."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import resolve_range
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "timetable:read"


def register(kit: ToolKit) -> None:
    """Register `list_lessons`."""

    @kit.tool(SCOPE)
    async def list_lessons(
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
        group_id: Annotated[UUID | None, Field(description="Only this group.")] = None,
        teacher_id: Annotated[
            UUID | None, Field(description="Only this teacher.")
        ] = None,
        room_id: Annotated[UUID | None, Field(description="Only this room.")] = None,
        status: Annotated[
            Literal["scheduled", "cancelled"] | None,
            Field(description="Only lessons in this status."),
        ] = None,
    ) -> dict[str, Any]:
        """List concrete lessons in a date range (default: today + 6 days)."""
        start, end = resolve_range(kit.deps, date_from, date_to, default_days=7)
        arguments = {
            "date_from": start,
            "date_to": end,
            "group_id": group_id,
            "teacher_id": teacher_id,
            "room_id": room_id,
            "status": status,
        }
        return await call_admin_tool(kit, "list_lessons", arguments)
