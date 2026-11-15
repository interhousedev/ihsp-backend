"""Write one `broadcast` notification per recipient, in batches of 1000."""

from collections.abc import Callable, Collection, Mapping
from uuid import UUID

from app.modules.admin.domain.broadcast import Broadcast
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.notifications import NotificationDraft, NotificationType

BATCH_SIZE = 1000


def broadcast_drafts(
    broadcast: Broadcast,
    recipients: Collection[UUID],
    *,
    bot_of: Mapping[UUID, UUID] | None = None,
) -> list[NotificationDraft]:
    """One notification per recipient; `bot_of` pins a recipient to a bot."""
    payload = broadcast.notification_payload()
    return [
        NotificationDraft(
            user_id=user_id,
            type=NotificationType.BROADCAST,
            payload=(
                {**payload, "bot_id": str(bot_of[user_id])}
                if bot_of and user_id in bot_of
                else payload
            ),
            dedupe_key=f"bc:{broadcast.id}:{user_id}",
            broadcast_id=broadcast.id,
        )
        for user_id in sorted(recipients, key=str)
    ]


class DeliverBroadcast:
    """Fans a broadcast out to its recipients; safe to run again (dedupe keys)."""

    def __init__(self, *, uow_factory: Callable[[], AdminUnitOfWork]) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, broadcast: Broadcast, recipients: Collection[UUID]) -> int:
        """Queue the notifications; each commit kicks the Telegram dispatcher."""
        drafts = broadcast_drafts(broadcast, recipients)
        for start in range(0, len(drafts), BATCH_SIZE):
            async with self.uow_factory() as uow:
                uow.notify(*drafts[start : start + BATCH_SIZE])
                await uow.commit()
        return len(drafts)
