"""Revoke a share or delete a short link (SL-7, SHR-6)."""

from uuid import UUID

from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.application.views import LinkView
from app.modules.links.domain.errors import LinkNotFoundError
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class RevokeLink:
    """Mark the owner's link revoked: it answers 410 from now on."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        builder: ResourceBuilder,
        invalidator: RoomCacheInvalidator,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.builder = builder
        self.invalidator = invalidator

    async def execute(self, actor: Actor, link_id: UUID) -> LinkView:
        """Revoke the link; repeating it keeps the first revocation time."""
        async with self.uow_factory() as uow:
            link = await uow.links.get(link_id)
            if link is None or link.owner_id != actor.user_id:
                raise LinkNotFoundError(params={"link_id": str(link_id)})
            link.revoke(self.clock.now())
            await uow.links.save(link)
            await uow.commit()
        if link.lesson_id is not None:
            await self.invalidator.lesson_id(link.lesson_id)
        return (await self.builder.link_views([link]))[0]
