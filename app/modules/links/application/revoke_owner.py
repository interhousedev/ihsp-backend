"""Revoke every link of a user whose account is closed (SHR-7, ID-28)."""

from uuid import UUID

from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


class RevokeOwner:
    """Revoke the owner's links and clear the room pages that listed them."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        invalidator: RoomCacheInvalidator,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.invalidator = invalidator
        self.clock = clock

    async def execute(self, user_id: UUID) -> int:
        """Return how many links were revoked."""
        now = self.clock.now()
        lesson_ids: list[UUID] = []
        async with self.uow_factory() as uow:
            links = await uow.links.active_by_owner(user_id)
            for link in links:
                link.revoke(now)
                await uow.links.save(link)
                if link.lesson_id is not None:
                    lesson_ids.append(link.lesson_id)
            await uow.commit()
        await self.invalidator.lesson_ids(lesson_ids)
        return len(links)
