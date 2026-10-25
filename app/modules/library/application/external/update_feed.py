"""Change a feed (partial update)."""

from uuid import UUID

from app.modules.library.domain.external_errors import FeedNotFoundError
from app.modules.library.domain.external_feed import Feed, FeedParams
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock


class UpdateFeed:
    """`PATCH /admin/library/unilibrary/feeds/{id}`: only the values that are given."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Take the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        feed_id: UUID,
        *,
        name: str | None = None,
        params: FeedParams | None = None,
        max_items: int | None = None,
    ) -> Feed:
        """Apply the given values; new filters drop the old size estimate."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            feed = await uow.external.get_feed(feed_id)
            if feed is None:
                raise FeedNotFoundError
            if name is not None:
                feed.name = name
            if max_items is not None:
                feed.max_items = max_items
            if params is not None and params != feed.params:
                feed.params = params
                feed.estimate = None
            feed.updated_at = self.clock.now()
            await uow.external.save_feed(feed)
            await uow.commit()
        return feed
