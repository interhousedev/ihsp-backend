"""Write one `broadcast` notification per recipient, in batches of 1000."""

from collections.abc import Callable, Collection
from uuid import UUID

from app.modules.admin.domain.broadcast import Broadcast
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.notifications import NotificationDraft, NotificationType

BATCH_SIZE = 1000


class DeliverBroadcast:
    """Fans a broadcast out to its recipients; safe to run again (dedupe keys)."""

    def __init__(self, *, uow_factory: Callable[[], AdminUnitOfWork]) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, broadcast: Broadcast, recipients: Collection[UUID]) -> int:
        """Queue the notifications; each commit kicks the Telegram dispatcher."""
        payload = broadcast.notification_payload()
        ordered = sorted(recipients, key=str)
        for start in range(0, len(ordered), BATCH_SIZE):
            drafts = [
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.BROADCAST,
                    payload=payload,
                    dedupe_key=f"bc:{broadcast.id}:{user_id}",
                    broadcast_id=broadcast.id,
                )
                for user_id in ordered[start : start + BATCH_SIZE]
            ]
            async with self.uow_factory() as uow:
                uow.notify(*drafts)
                await uow.commit()
        return len(ordered)
