"""Create a feed (storage only; no sync runs it)."""

from app.modules.library.domain.external_feed import Feed, FeedParams
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateFeed:
    """`POST /admin/library/unilibrary/feeds`: a new feed starts disabled."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Take the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, actor: Actor, *, name: str, params: FeedParams, max_items: int
    ) -> Feed:
        """Store and return the feed."""
        actor.require(Role.ADMIN)
        now = self.clock.now()
        feed = Feed(
            id=new_id(),
            name=name,
            params=params,
            max_items=max_items,
            created_at=now,
            updated_at=now,
        )
        async with self.uow_factory() as uow:
            await uow.external.add_feed(feed)
            await uow.commit()
        return feed
