"""POST /v1/admin/broadcasts/{broadcast_id}/preview."""

from uuid import UUID

from app.interfaces.http.v1.admin_broadcasts.dependencies import (
    AdminActor,
    ContainerDep,
)

from fastapi import Response


async def preview_broadcast(
    broadcast_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Send the broadcast to the caller's own Telegram."""
    await container.admin.preview_broadcast.execute(actor, broadcast_id)
    return Response(status_code=204)
