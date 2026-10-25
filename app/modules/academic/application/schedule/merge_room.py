"""Merge a mistyped room into the right one (ROOM-7, UF-ADM-16)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.results import RoomData
from app.modules.academic.application.schedule.room_views import build_room_data
from app.modules.academic.domain.schedule.errors import (
    RoomMergeInvalidError,
    RoomNotFoundError,
)
from app.shared.clock import Clock


class MergeRoom:
    """Move a room's entries and lessons to another room and archive it."""

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

    async def execute(self, source_id: UUID, into_room_id: UUID) -> RoomData:
        """Merge the source into the target and return the target room."""
        if source_id == into_room_id:
            raise RoomMergeInvalidError(params={"reason": "same-room"})
        async with self.uow_factory() as uow:
            source = await uow.rooms.get(source_id)
            target = await uow.rooms.get(into_room_id)
            if source is None or target is None:
                raise RoomNotFoundError()
            if target.status != "active":
                raise RoomMergeInvalidError(params={"reason": "target-archived"})
            await uow.entries.reassign_room(source.id, target.id)
            await uow.lessons.reassign_room(source.id, target.id)
            source.status = "archived"
            source.merged_into_id = target.id
            await uow.rooms.save(source)
            data = await build_room_data(
                uow, [target], today=today(self.clock), base_url=self.rooms_url
            )
            await uow.commit()
        await self.cache.invalidate({source.slug, target.slug})
        return data[0]
