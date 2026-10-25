"""POST /v1/admin/rooms/{id}/regenerate-pin."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.rooms.schemas import RoomResponse


async def regenerate_pin(
    room_id: UUID, container: ContainerDep, actor: AdminActor
) -> RoomResponse:
    """Give the room a new PIN."""
    room = await container.academic.schedule.regenerate_room_pin.execute(room_id)
    return RoomResponse.model_validate(room)
