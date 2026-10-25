"""The admin status page of the UniLibrary connection."""

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.external.views import StatusView
from app.modules.library.application.locale import resolve_locale
from app.modules.library.ports.external_monitor import ExternalMonitor
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory

LAST_CALLS = 20
HIDDEN_LIMIT = 100


class GetStatus:
    """`GET /admin/library/unilibrary/status`: breaker, calls, cache, hidden records."""

    def __init__(
        self,
        *,
        monitor: ExternalMonitor,
        uow_factory: UowFactory,
        cards: CardBuilder,
        identity: IdentityDirectory,
    ) -> None:
        """Take the Redis-backed monitor and what builds the hidden-record cards."""
        self.monitor = monitor
        self.uow_factory = uow_factory
        self.cards = cards
        self.identity = identity

    async def execute(
        self, actor: Actor, accept_language: str | None = None
    ) -> StatusView:
        """The state now; works while the integration is off."""
        actor.require(Role.ADMIN)
        locale = await resolve_locale(self.identity, actor, accept_language)
        async with self.uow_factory() as uow:
            ids = await uow.external.hidden_item_ids(limit=HIDDEN_LIMIT)
            found = await uow.items.get_many(ids)
            hidden = await self.cards.build(
                uow,
                [found[item_id] for item_id in ids if item_id in found],
                viewer=actor,
                locale=locale,
            )
        breaker = await self.monitor.breaker()
        return StatusView(
            breaker=breaker.state,
            last_calls=await self.monitor.last_calls(LAST_CALLS),
            cache=await self.monitor.cache_stats(),
            hidden_records=hidden,
        )
