"""Disable a link, share or lesson resource (ADM-13, SL-8, UF-ADM-10)."""

from uuid import UUID

from app.modules.links.application.moderation_views import ModerationViews, load_link
from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.application.views import ModerationView
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft


class DisableLink:
    """Disable the link without deleting it, keeping the evidence."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        views: ModerationViews,
        invalidator: RoomCacheInvalidator,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.views = views
        self.invalidator = invalidator
        self.clock = clock

    async def execute(self, actor: Actor, link_id: UUID, reason: str) -> ModerationView:
        """Disable the link and clear the room page of its lesson."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            link = await load_link(uow, link_id)
            link.disable(actor.user_id, reason.strip(), self.clock.now())
            await uow.links.save(link)
            uow.audit(
                AuditDraft(
                    type="link.disabled",
                    user_id=link.owner_id,
                    actor_id=actor.user_id,
                    metadata={
                        "link_id": str(link.id),
                        "slug": link.slug,
                        "reason": link.disabled_reason,
                    },
                )
            )
            await uow.commit()
        if link.lesson_id is not None:
            await self.invalidator.lesson_id(link.lesson_id)
        return (await self.views.build([link]))[0]
