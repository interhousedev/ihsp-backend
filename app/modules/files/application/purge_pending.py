"""Remove abandoned uploads and old rejected files (UF-WEB-18 2b)."""

from app.modules.files.domain.policy import PENDING_TTL
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

BATCH_FILES = 500


class PurgePending:
    """Hourly: pending rows older than 24 hours and rejected rows after 24 hours."""

    def __init__(
        self, *, uow_factory: UowFactory, storage: ObjectStorage, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._clock = clock

    async def execute(self) -> int:
        """Delete objects if present and the rows; return the number of rows."""
        cutoff = self._clock.now() - PENDING_TTL
        total = 0
        while True:
            async with self._uow_factory() as uow:
                batch = await uow.files.list_stale_uploads(cutoff, BATCH_FILES)
                if not batch:
                    break
                keys = [key for file in batch for key in file.storage_keys()]
                await self._storage.delete_many(keys)
                await uow.files.delete_rows([file.id for file in batch])
                await uow.commit()
            total += len(batch)
        return total
