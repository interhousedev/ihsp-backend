"""POST /v1/admin/broadcasts/{broadcast_id}/send."""

from uuid import UUID

from app.interfaces.http.v1.admin_broadcasts.dependencies import (
    AdminActor,
    ContainerDep,
)
from app.interfaces.http.v1.admin_broadcasts.schemas import (
    BroadcastResponse,
    SendBroadcastBody,
)


async def send_broadcast(
    broadcast_id: UUID,
    container: ContainerDep,
    actor: AdminActor,
    body: SendBroadcastBody | None = None,
) -> BroadcastResponse:
    """Send now, or schedule when `scheduled_at` is in the future."""
    scheduled_at = body.scheduled_at if body else None
    view = await container.admin.send_broadcast.execute(
        actor, broadcast_id, scheduled_at
    )
    return BroadcastResponse.from_view(view)
