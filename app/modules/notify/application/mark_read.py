"""Mark one notification as read (UF-WEB-15 step 3)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.notify.domain.errors import NotificationNotFoundError
from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock


class MarkRead:
    """Sets `read_at` on one of the user's notifications."""

    def __init__(
        self, *, uow_factory: Callable[[], NotifyUnitOfWork], clock: Clock
    ) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor, notification_id: UUID) -> None:
        """Mark read; reading twice is fine, someone else's row is not found."""
        async with self.uow_factory() as uow:
            found = await uow.notifications.mark_read(
                actor.user_id, notification_id, now=self.clock.now()
            )
            if not found:
                raise NotificationNotFoundError(
                    support_details=f"notification {notification_id}"
                )
            await uow.commit()
