"""Hand files over to another owner (the library adopts approved suggestions)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.files.domain.status import FileStatus
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


class TransferOwnership:
    """Change the owner of live files; the old owner's quota and deletes skip them."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, file_ids: Sequence[UUID], new_owner_id: UUID) -> None:
        """Move the files; unknown, deleted and already-moved ones are skipped."""
        async with self._uow_factory() as uow:
            for file in await uow.files.get_many(list(file_ids)):
                if file.status == FileStatus.DELETED or file.owner_id == new_owner_id:
                    continue
                file.transfer_to(new_owner_id, self._clock.now())
                await uow.files.save(file)
            await uow.commit()
