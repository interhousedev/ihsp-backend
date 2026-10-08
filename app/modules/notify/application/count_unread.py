"""Count unread notifications for the bell (UF-WEB-15)."""

from collections.abc import Callable

from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock


class CountUnread:
    """Returns how many visible notifications the user has not read."""

    def __init__(
        self, *, uow_factory: Callable[[], NotifyUnitOfWork], clock: Clock
    ) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor) -> int:
        """Return the unread count."""
        async with self.uow_factory() as uow:
            return await uow.notifications.unread_count(
                actor.user_id, now=self.clock.now()
            )
