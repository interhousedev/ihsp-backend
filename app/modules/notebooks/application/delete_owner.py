"""Job `notebooks.delete_owner(user_id)`: delete everything of a removed account."""

from uuid import UUID

from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.ports.unit_of_work import UowFactory

import structlog

BATCH = 100
log = structlog.get_logger(__name__)


class DeleteOwner:
    """Hard-deletes every notebook of a user at once (account deletion)."""

    def __init__(self, *, uow_factory: UowFactory, quota: QuotaService) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.quota = quota

    async def execute(self, user_id: UUID) -> int:
        """Delete the user's notebooks, deleted or not, and forget running outputs.

        Sources, passages, messages and outputs go with their notebook. A course
        workspace belongs to its course and stays, even when this user opened it
        first; only the user's own chat threads and progress in it are deleted.
        Returns how many notebooks were removed; running it again returns 0.
        """
        async with self.uow_factory() as uow:
            ids = await uow.notebooks.ids_for_owner(user_id)
        removed = 0
        for start in range(0, len(ids), BATCH):
            async with self.uow_factory() as uow:
                removed += await uow.notebooks.hard_delete(ids[start : start + BATCH])
                await uow.commit()
        async with self.uow_factory() as uow:
            await uow.messages.delete_for_user(user_id)
            await uow.progress.delete_for_user(user_id)
            await uow.commit()
        await self.quota.clear_running(user_id)
        await self.quota.pool(True).clear_running(user_id)
        log.info("notebooks_owner_deleted", count=removed)
        return removed
