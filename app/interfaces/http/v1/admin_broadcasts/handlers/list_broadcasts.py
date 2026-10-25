"""GET /v1/admin/broadcasts."""

from typing import Annotated, Literal

from app.interfaces.http.v1.admin_broadcasts.dependencies import (
    AdminActor,
    ContainerDep,
)
from app.interfaces.http.v1.admin_broadcasts.schemas import BroadcastResponse
from app.modules.admin.domain.broadcast import BroadcastStatus
from app.shared.pagination import Page

from fastapi import Query


async def list_broadcasts(
    container: ContainerDep,
    actor: AdminActor,
    status: Literal["draft", "scheduled", "sending", "sent", "cancelled"] | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[BroadcastResponse]:
    """List broadcasts, newest first."""
    page = await container.admin.list_broadcasts.execute(
        actor,
        status=BroadcastStatus(status) if status else None,
        cursor=cursor,
        limit=limit,
    )
    return Page[BroadcastResponse](
        items=[BroadcastResponse.from_view(view) for view in page.items],
        next_cursor=page.next_cursor,
    )
