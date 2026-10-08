"""POST /v1/admin/broadcasts/{broadcast_id}/cancel."""

from uuid import UUID

from app.interfaces.http.v1.admin_broadcasts.dependencies import (
    AdminActor,
    ContainerDep,
)
from app.interfaces.http.v1.admin_broadcasts.schemas import BroadcastResponse


async def cancel_broadcast(
    broadcast_id: UUID, container: ContainerDep, actor: AdminActor
) -> BroadcastResponse:
    """Cancel a scheduled broadcast."""
    view = await container.admin.cancel_broadcast.execute(actor, broadcast_id)
    return BroadcastResponse.from_view(view)
