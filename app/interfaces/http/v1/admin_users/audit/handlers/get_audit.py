"""GET /v1/admin/audit: the audit log."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep
from app.interfaces.http.v1.id.schemas import AuditItemResponse
from app.shared.pagination import Page

from fastapi import Query


async def get_audit(
    _admin: AdminDep,
    auth: AuthDep,
    user_id: UUID | None = None,
    type: str | None = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[AuditItemResponse]:
    """Newest first; filter by user, type and period."""
    page = await auth.list_audit.execute(
        user_id=user_id,
        type=type,
        since=since,
        until=until,
        cursor=cursor,
        limit=limit,
    )
    items = [AuditItemResponse.of(event, page.actors) for event in page.items]
    return Page[AuditItemResponse](items=items, next_cursor=page.next_cursor)
