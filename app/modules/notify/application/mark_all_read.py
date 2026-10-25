"""Mark every notification as read (UF-WEB-15 step 4)."""

from collections.abc import Callable

from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock


class MarkAllRead:
    """Sets `read_at` on all unread notifications of the user."""

    def __init__(
        self, *, uow_factory: Callable[[], NotifyUnitOfWork], clock: Clock
    ) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor) -> int:
        """Mark all read and return how many changed."""
        async with self.uow_factory() as uow:
            changed = await uow.notifications.mark_all_read(
                actor.user_id, now=self.clock.now()
            )
            await uow.commit()
        return changed
