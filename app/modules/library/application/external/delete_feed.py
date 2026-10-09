"""Delete a feed."""

from uuid import UUID

from app.modules.library.domain.external_errors import FeedNotFoundError
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


class DeleteFeed:
    """`DELETE /admin/library/unilibrary/feeds/{id}`."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Take the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, feed_id: UUID) -> None:
        """Remove the feed; the records it created stay (they are ordinary items)."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            if not await uow.external.delete_feed(feed_id):
                raise FeedNotFoundError
            await uow.commit()
