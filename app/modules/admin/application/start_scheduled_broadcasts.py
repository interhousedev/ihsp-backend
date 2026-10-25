"""Start broadcasts whose time has come (task admin.start_scheduled_broadcasts)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.admin.application.deliver_broadcast import DeliverBroadcast
from app.modules.admin.application.resolve_audience import ResolveAudience
from app.modules.admin.application.send_broadcast import broadcast_sent_audit
from app.modules.admin.domain.broadcast import Broadcast, BroadcastStats
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.clock import Clock

import structlog

log = structlog.get_logger(__name__)


class StartScheduledBroadcasts:
    """Moves due scheduled broadcasts to `sending` and writes their notifications."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        resolver: ResolveAudience,
        deliver: DeliverBroadcast,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.resolver = resolver
        self.deliver = deliver
        self.clock = clock

    async def execute(self) -> int:
        """Start every due broadcast and return how many started."""
        started: list[tuple[Broadcast, set[UUID]]] = []
        async with self.uow_factory() as uow:
            for broadcast in await uow.broadcasts.claim_scheduled(self.clock.now()):
                recipients = await self.resolver.execute(broadcast.audience)
                if not recipients:
                    log.warning("broadcast_without_recipients", id=str(broadcast.id))
                    broadcast.start_sending(0)
                    broadcast.finish(BroadcastStats(0, 0, 0, 0))
                else:
                    broadcast.start_sending(len(recipients))
                    started.append((broadcast, recipients))
                await uow.broadcasts.save(broadcast)
                uow.audit(
                    broadcast_sent_audit(
                        broadcast,
                        actor_id=broadcast.author_id,
                        recipients=len(recipients),
                    )
                )
            await uow.commit()
        for broadcast, recipients in started:
            await self.deliver.execute(broadcast, recipients)
        return len(started)
