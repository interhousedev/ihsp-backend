"""Close broadcasts when every notification is final (task admin.finish_broadcasts)."""

from collections.abc import Callable

from app.modules.admin.application.deliver_broadcast import DeliverBroadcast
from app.modules.admin.application.resolve_audience import ResolveAudience
from app.modules.admin.domain.broadcast import Broadcast, BroadcastStats
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork

import structlog

log = structlog.get_logger(__name__)


class FinishBroadcasts:
    """Marks `sending` broadcasts `sent` and freezes their stats."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        resolver: ResolveAudience,
        deliver: DeliverBroadcast,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.resolver = resolver
        self.deliver = deliver

    async def execute(self) -> int:
        """Finish what is done, resume what was cut short; return how many finished."""
        finished = 0
        incomplete: list[Broadcast] = []
        async with self.uow_factory() as uow:
            for broadcast in await uow.broadcasts.list_sending():
                counts = await uow.deliveries.counts(broadcast.id)
                expected = broadcast.stats.total if broadcast.stats else 0
                if counts.total < expected:
                    incomplete.append(broadcast)
                elif counts.open == 0:
                    broadcast.finish(
                        BroadcastStats(
                            total=counts.total,
                            sent=counts.sent,
                            failed=counts.failed,
                            blocked=counts.blocked,
                        )
                    )
                    await uow.broadcasts.save(broadcast)
                    finished += 1
            await uow.commit()
        for broadcast in incomplete:
            log.warning("broadcast_resumed", id=str(broadcast.id))
            recipients = await self.resolver.execute(broadcast.audience)
            await self.deliver.execute(broadcast, recipients)
        return finished
