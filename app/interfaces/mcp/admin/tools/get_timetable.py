"""Administration tool `get_timetable`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "timetable:read"


def register(kit: ToolKit) -> None:
    """Register `get_timetable`."""

    @kit.tool(SCOPE)
    async def get_timetable(
        group_id: Annotated[UUID | None, Field(description="Only this group.")] = None,
        teacher_id: Annotated[
            UUID | None, Field(description="Only this teacher.")
        ] = None,
        room_id: Annotated[UUID | None, Field(description="Only this room.")] = None,
    ) -> dict[str, Any]:
        """Show recurring weekly timetable entries, filtered by group, teacher, room."""
        arguments = {"group_id": group_id, "teacher_id": teacher_id, "room_id": room_id}
        return await call_admin_tool(kit, "get_timetable", arguments)
