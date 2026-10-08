"""PATCH /v1/admin/rooms/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.rooms.schemas import (
    RoomRenameBody,
    RoomResponse,
)


async def rename_room(
    room_id: UUID, body: RoomRenameBody, container: ContainerDep, actor: AdminActor
) -> RoomResponse:
    """Rename a room; its address changes too."""
    room = await container.academic.schedule.rename_room.execute(room_id, body.name)
    return RoomResponse.model_validate(room)
