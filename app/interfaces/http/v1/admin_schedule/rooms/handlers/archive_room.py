"""POST /v1/admin/rooms/{id}/archive."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.rooms.schemas import RoomResponse


async def archive_room(
    room_id: UUID, container: ContainerDep, actor: AdminActor
) -> RoomResponse:
    """Archive a room no future lesson uses."""
    room = await container.academic.schedule.archive_room.execute(room_id)
    return RoomResponse.model_validate(room)
