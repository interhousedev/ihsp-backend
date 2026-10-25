"""GET /v1/id/me/activity: the caller's security log."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep
from app.interfaces.http.v1.id.schemas import AuditItemResponse
from app.shared.pagination import Page

from fastapi import Query


async def get_activity(
    actor: ActorDep,
    auth: AuthDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[AuditItemResponse]:
    """Newest events first."""
    page = await auth.list_activity.execute(actor, cursor=cursor, limit=limit)
    items = [AuditItemResponse.of(event, page.actors) for event in page.items]
    return Page[AuditItemResponse](items=items, next_cursor=page.next_cursor)
