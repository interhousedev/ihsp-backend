"""Administration tool `missing_attendance`."""

from datetime import timedelta
from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import resolve_range
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.clock import local_today

from pydantic import Field

SCOPE = "attendance:read"


def register(kit: ToolKit) -> None:
    """Register `missing_attendance`."""

    @kit.tool(SCOPE)
    async def missing_attendance(
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
        teacher_id: Annotated[
            UUID | None, Field(description="Only this teacher.")
        ] = None,
    ) -> dict[str, Any]:
        """List finished lessons whose attendance was not submitted.

        Default range: the last 7 days up to today.
        """
        today = local_today(kit.deps.clock)
        start, end = resolve_range(
            kit.deps,
            date_from or today - timedelta(days=6),
            date_to or today,
            default_days=7,
        )
        arguments = {"date_from": start, "date_to": end, "teacher_id": teacher_id}
        return await call_admin_tool(kit, "missing_attendance", arguments)
