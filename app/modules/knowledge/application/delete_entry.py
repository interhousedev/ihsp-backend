"""Delete a knowledge entry (administrator)."""

from uuid import UUID

from app.modules.knowledge.domain.errors import KnowledgeEntryNotFoundError
from app.modules.knowledge.ports.unit_of_work import UowFactory


class DeleteEntry:
    """Delete an entry.

    Its vector stays in `vectors.embeddings`: vectors belong to the text hash and may
    be shared with other modules, so the vectors module owns their lifetime.
    """

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, entry_id: UUID) -> None:
        """Delete the entry."""
        async with self._uow_factory() as uow:
            if await uow.entries.get(entry_id) is None:
                raise KnowledgeEntryNotFoundError()
            await uow.entries.delete(entry_id)
            await uow.commit()
