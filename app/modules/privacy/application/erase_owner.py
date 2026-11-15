"""Task body: remove a user's personal data at the end of the deletion window."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.files.ports.storage import ObjectStorage
from app.modules.privacy.ports.unit_of_work import UowFactory
from app.shared.contracts.privacy import ErasureGateway
from app.shared.personal_data import PersonalData

EXPORT_PAGE = 1000


class EraseOwner:
    """Delete the archives, erase every module's rows, close the request."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        sources: Sequence[PersonalData],
        storage: ObjectStorage,
        erasure: ErasureGateway,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._sources = sources
        self._storage = storage
        self._erasure = erasure

    async def execute(self, user_id: UUID) -> int:
        """Return how many rows were deleted or cleared."""
        async with self._uow_factory() as uow:
            jobs = await uow.exports.list_of(user_id, limit=EXPORT_PAGE)
        await self._storage.delete_many([j.storage_key for j in jobs if j.storage_key])
        touched = 0
        for source in self._sources:
            touched += await source.erase(user_id)
        await self._erasure.complete(user_id)
        return touched
