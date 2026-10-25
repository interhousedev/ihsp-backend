"""Delete every file of a user now (account deletion)."""

from uuid import UUID

from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

BATCH_FILES = 500


class DeleteOwnerFiles:
    """Task ``files.delete_owner``: objects, sidecars and search vectors go."""

    def __init__(
        self, *, uow_factory: UowFactory, storage: ObjectStorage, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._clock = clock

    async def execute(self, user_id: UUID) -> int:
        """Delete the user's files in batches; return how many."""
        total = 0
        while True:
            async with self._uow_factory() as uow:
                batch = await uow.files.list_for_owner_all(user_id, BATCH_FILES)
                if not batch:
                    break
                keys = [key for file in batch for key in file.storage_keys()]
                await self._storage.delete_many(keys)
                await uow.files.mark_deleted(
                    [file.id for file in batch], self._clock.now()
                )
                await uow.commit()
            total += len(batch)
        return total
