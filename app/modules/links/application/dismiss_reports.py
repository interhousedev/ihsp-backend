"""Dismiss the reports of a link (UF-ADM-10, alternative 2a)."""

from uuid import UUID

from app.modules.links.application.moderation_views import ModerationViews, load_link
from app.modules.links.application.views import ModerationView
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft


class DismissReports:
    """Remove the link from the queue until the next report arrives."""

    def __init__(
        self, *, uow_factory: UowFactory, views: ModerationViews, clock: Clock
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.views = views
        self.clock = clock

    async def execute(self, actor: Actor, link_id: UUID) -> ModerationView:
        """Mark the reports reviewed."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            link = await load_link(uow, link_id)
            link.dismiss_reports(self.clock.now())
            await uow.links.save(link)
            uow.audit(
                AuditDraft(
                    type="link.reports_dismissed",
                    user_id=link.owner_id,
                    actor_id=actor.user_id,
                    metadata={"link_id": str(link.id), "slug": link.slug},
                )
            )
            await uow.commit()
        return (await self.views.build([link]))[0]
