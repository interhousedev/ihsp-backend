"""Administration tool `audit_log`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "audit:read"


def register(kit: ToolKit) -> None:
    """Register `audit_log`."""

    @kit.tool(SCOPE)
    async def audit_log(
        event_type: Annotated[
            str | None,
            Field(max_length=64, description="Event type, e.g. role.granted."),
        ] = None,
        user_id: Annotated[
            UUID | None, Field(description="Only events about this user.")
        ] = None,
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Most events.")] = 50,
    ) -> dict[str, Any]:
        """List audit events, newest first: type, user, actor, time and details."""
        check_range(date_from, date_to)
        arguments = {
            "type": event_type,
            "user_id": user_id,
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
        }
        return await call_admin_tool(kit, "audit_log", arguments)
