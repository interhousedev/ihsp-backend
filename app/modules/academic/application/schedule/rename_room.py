"""Rename a room; its address changes with it (ROOM-7)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.results import RoomData
from app.modules.academic.application.schedule.room_views import build_room_data
from app.modules.academic.domain.schedule.errors import (
    RoomNotFoundError,
    RoomSlugTakenError,
)
from app.modules.academic.domain.schedule.room import clean_room_name, room_slug
from app.shared.clock import Clock


class RenameRoom:
    """Change a room's name and slug; the new slug must be free."""

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

    async def execute(self, room_id: UUID, name: str) -> RoomData:
        """Rename the room and clear its cached pages."""
        clean = clean_room_name(name)
        slug = room_slug(clean)
        async with self.uow_factory() as uow:
            room = await uow.rooms.get(room_id)
            if room is None:
                raise RoomNotFoundError()
            clash = await uow.rooms.get_by_slug(slug)
            if clash is not None and clash.id != room.id:
                raise RoomSlugTakenError(params={"slug": slug})
            old_slug = room.slug
            room.name, room.slug = clean, slug
            await uow.rooms.save(room)
            data = await build_room_data(
                uow, [room], today=today(self.clock), base_url=self.rooms_url
            )
            await uow.commit()
        await self.cache.invalidate({old_slug, slug})
        return data[0]
