"""GET /v1/admin/mcp/activity/summary: calls and errors per tool."""

from datetime import datetime
from typing import Annotated

from app.interfaces.http.v1.admin_mcp.schemas import (
    McpActivitySummary,
    McpToolSummaryItem,
)
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep

from fastapi import Query


async def get_summary(
    actor: AdminDep,
    auth: AuthDep,
    ctx: CtxDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> McpActivitySummary:
    """The last 7 days unless `from` says otherwise."""
    rows = await auth.list_mcp_activity.summary(actor, ctx, from_, to)
    return McpActivitySummary(
        items=[
            McpToolSummaryItem(
                server=row.server, tool=row.tool, calls=row.calls, errors=row.errors
            )
            for row in rows
        ]
    )
