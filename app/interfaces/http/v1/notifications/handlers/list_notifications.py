"""GET /v1/notifications."""

from typing import Annotated, Literal

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.notifications.schemas import NotificationItemResponse
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.shared.actor import Actor
from app.shared.pagination import Page

from fastapi import Depends, Query


async def list_notifications(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
    filter: Annotated[Literal["all", "activity", "announcements"], Query()] = "all",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[NotificationItemResponse]:
    """List the caller's notifications, newest first."""
    page = await container.notify.list_notifications.execute(
        actor, NotificationFilter(filter), cursor=cursor, limit=limit
    )
    return Page[NotificationItemResponse](
        items=[
            NotificationItemResponse(
                id=item.id,
                type=item.type,
                title=item.title,
                body=item.body,
                link=item.link,
                created_at=item.created_at,
                read_at=item.read_at,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )
