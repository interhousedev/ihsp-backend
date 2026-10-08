"""Archive a room no future lesson uses (ROOM-7)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.results import RoomData
from app.modules.academic.application.schedule.room_views import build_room_data
from app.modules.academic.domain.schedule.errors import (
    RoomInUseError,
    RoomNotFoundError,
)
from app.shared.clock import Clock


class ArchiveRoom:
    """Hide a room that no scheduled lesson in the future uses."""

    def __init__(self, uow_factory: UowFactory, clock: Clock, rooms_url: str) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.rooms_url = rooms_url

    async def execute(self, room_id: UUID) -> RoomData:
        """Archive the room or raise RoomInUseError."""
        async with self.uow_factory() as uow:
            room = await uow.rooms.get(room_id)
            if room is None:
                raise RoomNotFoundError()
            if await uow.lessons.count_future_in_room(room.id, self.clock.now()) > 0:
                raise RoomInUseError(params={"room_id": str(room.id)})
            room.status = "archived"
            await uow.rooms.save(room)
            data = await build_room_data(
                uow, [room], today=today(self.clock), base_url=self.rooms_url
            )
            await uow.commit()
        return data[0]
