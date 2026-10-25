"""Use case: hard-delete Administration chats after 90 days (AI-12)."""

from collections.abc import Callable
from datetime import timedelta

from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.clock import Clock

RETENTION = timedelta(days=90)


class PurgeAdminChats:
    """Deletes old Administration chats with their messages."""

    def __init__(
        self, *, uow_factory: Callable[[], AiUnitOfWork], clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self) -> int:
        """Delete chats whose last message is older than 90 days; return the count."""
        cutoff = self.clock.now() - RETENTION
        async with self.uow_factory() as uow:
            removed = await uow.chats.purge_admin_chats(cutoff)
            await uow.commit()
        return removed
