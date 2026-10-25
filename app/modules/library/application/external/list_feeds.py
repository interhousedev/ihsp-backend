"""List the stored feeds (Administration)."""

from app.modules.library.domain.external_feed import Feed
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


class ListFeeds:
    """`GET /admin/library/unilibrary/feeds`."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Take the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor) -> list[Feed]:
        """All feeds, oldest first."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            return await uow.external.list_feeds()
