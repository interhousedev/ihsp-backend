"""GET /v1/admin/broadcasts/{broadcast_id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_broadcasts.dependencies import (
    AdminActor,
    ContainerDep,
)
from app.interfaces.http.v1.admin_broadcasts.schemas import BroadcastResponse


async def get_broadcast(
    broadcast_id: UUID, container: ContainerDep, actor: AdminActor
) -> BroadcastResponse:
    """Return one broadcast with its stats."""
    view = await container.admin.get_broadcast.execute(actor, broadcast_id)
    return BroadcastResponse.from_view(view)
