"""GET /v1/admin/mcp/activity: every MCP call, with filters."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admin_mcp.schemas import (
    AdminMcpActivityItem,
    AdminMcpActivityPage,
)
from app.interfaces.http.v1.id.connectors.schemas import McpOutcome
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep
from app.modules.identity.ports.mcp_call_log import McpCallFilter

from fastapi import Query


async def list_activity(
    actor: AdminDep,
    auth: AuthDep,
    ctx: CtxDep,
    user_id: UUID | None = None,
    connector_id: UUID | None = None,
    server: Literal["student", "lms", "admin"] | None = None,
    tool: Annotated[str | None, Query(max_length=100)] = None,
    outcome: McpOutcome | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> AdminMcpActivityPage:
    """Newest first, 50 per page; every read writes `mcp.activity_viewed`."""
    where = McpCallFilter(
        user_id=user_id,
        connector_id=connector_id,
        server=server,
        tool=tool,
        outcome=outcome,
        since=from_,
        until=to,
    )
    page = await auth.list_mcp_activity.for_admin(actor, ctx, where, cursor=cursor)
    return AdminMcpActivityPage(
        items=[AdminMcpActivityItem.of(entry) for entry in page.items],
        next_cursor=page.next_cursor,
    )
