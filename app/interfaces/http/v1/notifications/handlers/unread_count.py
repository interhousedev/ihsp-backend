"""GET /v1/notifications/unread-count."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.notifications.schemas import UnreadCountResponse
from app.shared.actor import Actor

from fastapi import Depends


async def unread_count(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> UnreadCountResponse:
    """Return how many notifications the caller has not read."""
    return UnreadCountResponse(count=await container.notify.count_unread.execute(actor))
