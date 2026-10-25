"""Send a broadcast now or schedule it (ADM-11, UF-ADM-08 step 4)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.admin.application.broadcast_view import (
    BroadcastPresenter,
    BroadcastView,
)
from app.modules.admin.application.deliver_broadcast import DeliverBroadcast
from app.modules.admin.application.resolve_audience import ResolveAudience
from app.modules.admin.domain.broadcast import Broadcast
from app.modules.admin.domain.errors import (
    BroadcastEmptyAudienceError,
    BroadcastTimeInvalidError,
)
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft

AUDIT_BROADCAST_SENT = "broadcast.sent"


def broadcast_sent_audit(
    broadcast: Broadcast, *, actor_id: UUID | None, recipients: int
) -> AuditDraft:
    """The audit event written when delivery starts."""
    return AuditDraft(
        type=AUDIT_BROADCAST_SENT,
        actor_id=actor_id,
        metadata={
            "broadcast_id": str(broadcast.id),
            "author_id": str(broadcast.author_id),
            "recipients": recipients,
        },
    )


class SendBroadcast:
    """Starts delivery, or schedules the broadcast for a future time."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        resolver: ResolveAudience,
        deliver: DeliverBroadcast,
        presenter: BroadcastPresenter,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.resolver = resolver
        self.deliver = deliver
        self.presenter = presenter
        self.clock = clock

    async def execute(
        self, actor: Actor, broadcast_id: UUID, scheduled_at: datetime | None = None
    ) -> BroadcastView:
        """Schedule when `scheduled_at` is in the future, otherwise send now."""
        actor.require(Role.ADMIN)
        if scheduled_at is not None and scheduled_at.tzinfo is None:
            raise BroadcastTimeInvalidError(support_details="naive scheduled_at")
        if scheduled_at is not None and scheduled_at > self.clock.now():
            return await self._schedule(broadcast_id, scheduled_at)
        return await self._send_now(actor, broadcast_id)

    async def _schedule(self, broadcast_id: UUID, at: datetime) -> BroadcastView:
        async with self.uow_factory() as uow:
            broadcast = await uow.broadcasts.get(broadcast_id, for_update=True)
            broadcast.schedule(at)
            await uow.broadcasts.save(broadcast)
            await uow.commit()
            return (await self.presenter.present(uow, [broadcast]))[0]

    async def _send_now(self, actor: Actor, broadcast_id: UUID) -> BroadcastView:
        async with self.uow_factory() as uow:
            broadcast = await uow.broadcasts.get(broadcast_id, for_update=True)
            broadcast.ensure_sendable()
            recipients = await self.resolver.execute(broadcast.audience)
            if not recipients:
                raise BroadcastEmptyAudienceError(
                    support_details=f"broadcast {broadcast_id}"
                )
            broadcast.start_sending(len(recipients))
            await uow.broadcasts.save(broadcast)
            uow.audit(
                broadcast_sent_audit(
                    broadcast, actor_id=actor.user_id, recipients=len(recipients)
                )
            )
            await uow.commit()
        await self.deliver.execute(broadcast, recipients)
        async with self.uow_factory() as uow:
            return (await self.presenter.present(uow, [broadcast]))[0]
