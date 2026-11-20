"""Administration tools `ai_request_stats` and `ai_spend`."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "audit:read"
RequestId = Annotated[
    str | None, Field(max_length=96, description="Only this AI request id.")
]
UserId = Annotated[UUID | None, Field(description="Only calls of this user.")]


def register(kit: ToolKit) -> None:
    """Register the analytics tools."""

    @kit.tool(SCOPE)
    async def ai_request_stats(
        start: DateFromParam = None,
        end: DateToParam = None,
        group_by: Annotated[
            Literal["request", "day", "user", "pipeline"],
            Field(description="How to group the calls."),
        ] = "request",
        request_id: RequestId = None,
        pipeline: Annotated[
            str | None, Field(max_length=32, description="Only this pipeline.")
        ] = None,
    ) -> dict[str, Any]:
        """Averages (tokens, characters, tool calls), failures and cost (micro-USD)."""
        arguments = {
            "start": start,
            "end": end,
            "group_by": group_by,
            "request_id": request_id,
            "pipeline": pipeline,
        }
        return await call_admin_tool(kit, "ai_request_stats", arguments)

    @kit.tool(SCOPE)
    async def ai_spend(
        start: DateFromParam = None,
        end: DateToParam = None,
        by: Annotated[
            Literal["day", "request", "user"], Field(description="How to group spend.")
        ] = "day",
        request_id: RequestId = None,
        user_id: UserId = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Most rows.")] = 20,
    ) -> dict[str, Any]:
        """Spend in micro-USD per day, request or user, most expensive first."""
        arguments = {
            "start": start,
            "end": end,
            "by": by,
            "request_id": request_id,
            "user_id": user_id,
            "limit": limit,
        }
        return await call_admin_tool(kit, "ai_spend", arguments)
