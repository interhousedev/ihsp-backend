"""Replace a room's PIN; old PINs and bookmarks stop working (ROOM-6)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.results import RoomData
from app.modules.academic.application.schedule.room_views import build_room_data
from app.modules.academic.domain.schedule.errors import RoomNotFoundError
from app.shared.clock import Clock
from app.shared.ids import random_digits

PIN_LENGTH = 6


class RegenerateRoomPin:
    """Give a room a new random 6-digit PIN."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        cache: RoomPageCache,
        rooms_url: str,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.cache = cache
        self.rooms_url = rooms_url

    async def execute(self, room_id: UUID) -> RoomData:
        """Set a PIN different from the old one and clear the cached pages."""
        async with self.uow_factory() as uow:
            room = await uow.rooms.get(room_id)
            if room is None:
                raise RoomNotFoundError()
            new_pin = random_digits(PIN_LENGTH)
            while new_pin == room.pin:
                new_pin = random_digits(PIN_LENGTH)
            room.pin = new_pin
            room.pin_changed_at = self.clock.now()
            await uow.rooms.save(room)
            data = await build_room_data(
                uow, [room], today=today(self.clock), base_url=self.rooms_url
            )
            await uow.commit()
        await self.cache.invalidate({room.slug})
        return data[0]
