"""Feed actions: enable and disable work, dry run and run need the sync."""

from uuid import UUID

from app.modules.library.domain.external_errors import (
    ExternalSyncUnavailableError,
    FeedNotFoundError,
)
from app.modules.library.domain.external_feed import Feed, FeedAction
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock


class RunFeedAction:
    """`POST /admin/library/unilibrary/feeds/{id}/{action}`.

    The periodic sync is not built in this release, so `dry-run` and `run` answer
    `409 library/external-sync-unavailable`; `enable` and `disable` only flip the flag.
    """

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Take the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor, feed_id: UUID, action: FeedAction) -> Feed:
        """Do the action and return the feed."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            feed = await uow.external.get_feed(feed_id)
            if feed is None:
                raise FeedNotFoundError
            if action in (FeedAction.DRY_RUN, FeedAction.RUN):
                raise ExternalSyncUnavailableError(
                    params={"action": action.value},
                    support_details="feed sync is not built",
                )
            feed.enabled = action is FeedAction.ENABLE
            feed.updated_at = self.clock.now()
            await uow.external.save_feed(feed)
            await uow.commit()
        return feed
