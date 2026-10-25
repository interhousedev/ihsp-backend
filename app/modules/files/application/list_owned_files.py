"""List an owner's ready files for other modules (MCP, assistant)."""

from uuid import UUID

from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FileRef

MAX_LIMIT = 100


class ListOwnedFiles:
    """Ready, non-deleted files of one owner, newest first."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """Return up to ``limit`` files (at most 100)."""
        size = max(1, min(limit, MAX_LIMIT))
        async with self._uow_factory() as uow:
            files = await uow.files.list_ready(owner_id, size)
        return [file.to_ref() for file in files]
