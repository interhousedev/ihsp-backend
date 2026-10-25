"""Send a broadcast preview to the admin's own Telegram (UF-ADM-08 step 3)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.admin.domain.errors import BroadcastNoTelegramError
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType


class PreviewBroadcast:
    """Queues a `broadcast` notification for the caller only.

    It has no broadcast_id, so it never counts in the stats, and the center hides
    it. The dispatcher sends it to every Telegram account of the admin.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        identity: IdentityDirectory,
    ) -> None:
        """Store the unit of work factory and the identity directory."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(self, actor: Actor, broadcast_id: UUID) -> None:
        """Queue the preview; the admin needs a linked Telegram account."""
        actor.require(Role.ADMIN)
        accounts = await self.identity.telegram_accounts(actor.user_id)
        if not any(not account.blocked for account in accounts):
            raise BroadcastNoTelegramError(support_details=str(actor.user_id))
        async with self.uow_factory() as uow:
            broadcast = await uow.broadcasts.get(broadcast_id)
            uow.notify(
                NotificationDraft(
                    user_id=actor.user_id,
                    type=NotificationType.BROADCAST,
                    payload=broadcast.notification_payload(preview=True),
                    dedupe_key=f"bcp:{broadcast.id}:{new_id()}",
                )
            )
            await uow.commit()
