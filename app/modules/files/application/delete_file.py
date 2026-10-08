"""Delete a file now: object, text sidecar and row state (UF-WEB-18 step 4)."""

from uuid import UUID

from app.modules.files.application.access import require_owner_editable
from app.modules.files.domain.used_by import UsedBy
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory
from app.modules.files.ports.usage_resolver import UsageResolver
from app.shared.actor import Actor
from app.shared.clock import Clock


class DeleteFile:
    """Soft-delete the owner's file and remove its objects immediately."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        storage: ObjectStorage,
        usage: UsageResolver,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._usage = usage
        self._clock = clock

    async def execute(self, actor: Actor, file_id: UUID) -> list[UsedBy]:
        """Return the places that used the file before it was deleted."""
        async with self._uow_factory() as uow:
            file = require_owner_editable(await uow.files.get(file_id), actor)
            used_by = (await self._usage.used_by([file.id])).get(file.id, [])
            # Objects first: a failure leaves a live row the user can delete again.
            await self._storage.delete_many(file.storage_keys())
            await uow.files.mark_deleted([file.id], self._clock.now())
            await uow.commit()
        return used_by
