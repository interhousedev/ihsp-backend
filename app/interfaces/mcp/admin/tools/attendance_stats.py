"""Administration tool `attendance_stats`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import resolve_range
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "attendance:read"


def register(kit: ToolKit) -> None:
    """Register `attendance_stats`."""

    @kit.tool(SCOPE)
    async def attendance_stats(
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
        group_id: Annotated[UUID | None, Field(description="Only this group.")] = None,
    ) -> dict[str, Any]:
        """Summarize absences in a date range (default: today + 6 days)."""
        start, end = resolve_range(kit.deps, date_from, date_to, default_days=7)
        arguments = {"date_from": start, "date_to": end, "group_id": group_id}
        return await call_admin_tool(kit, "attendance_stats", arguments)
