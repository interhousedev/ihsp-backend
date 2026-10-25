"""Delete a file for good on behalf of another module (library clean-up)."""

from uuid import UUID

from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory


class RemoveFile:
    """Objects first, then the row; safe to repeat."""

    def __init__(self, *, uow_factory: UowFactory, storage: ObjectStorage) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage

    async def execute(self, file_id: UUID) -> None:
        """Remove the content, the text sidecar and the row; unknown ids are fine.

        There is no access check: the calling module already decided. A failure in
        storage leaves the row, so the call can be repeated.
        """
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
            if file is None:
                return
            await self._storage.delete_many(file.storage_keys())
            await uow.files.delete_rows([file.id])
            await uow.commit()
