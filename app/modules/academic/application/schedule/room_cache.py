"""Clearing cached room pages after a change (ROOM-8)."""

from collections.abc import Collection
from uuid import UUID

from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)


async def invalidate_room_pages(
    uow: ScheduleUnitOfWork,
    cache: RoomPageCache,
    room_ids: Collection[UUID | None],
) -> None:
    """Clear the cached pages of the rooms once the transaction commits."""
    ids = {room_id for room_id in room_ids if room_id is not None}
    if not ids:
        return
    slugs = sorted(room.slug for room in (await uow.rooms.get_many(ids)).values())
    if not slugs:
        return

    async def hook() -> None:
        await cache.invalidate(slugs)

    uow.after_commit(hook)
