"""GET /v1/id/me/connectors/activity: the caller's own MCP calls."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.id.connectors.schemas import (
    McpActivityItem,
    McpActivityPage,
    McpOutcome,
)
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep

from fastapi import Query


async def get_activity(
    actor: ActorDep,
    auth: AuthDep,
    connector_id: UUID | None = None,
    tool: Annotated[str | None, Query(max_length=100)] = None,
    outcome: McpOutcome | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> McpActivityPage:
    """Newest first, 50 per page; scoped to the caller whatever the filter names."""
    page = await auth.list_mcp_activity.for_user(
        actor.user_id,
        connector_id=connector_id,
        tool=tool,
        outcome=outcome,
        since=from_,
        until=to,
        cursor=cursor,
    )
    return McpActivityPage(
        items=[McpActivityItem.of(entry) for entry in page.items],
        next_cursor=page.next_cursor,
    )
