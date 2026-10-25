"""Read one knowledge entry (administrator)."""

from uuid import UUID

from app.modules.knowledge.domain.entry import KnowledgeEntry
from app.modules.knowledge.domain.errors import KnowledgeEntryNotFoundError
from app.modules.knowledge.ports.unit_of_work import UowFactory


class GetEntry:
    """Return an entry by id."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, entry_id: UUID) -> KnowledgeEntry:
        """Return the entry."""
        async with self._uow_factory() as uow:
            entry = await uow.entries.get(entry_id)
        if entry is None:
            raise KnowledgeEntryNotFoundError()
        return entry
