"""Search the owner's files by their extracted text (assistant, global search)."""

from typing import Any
from uuid import UUID

from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory

MIN_QUERY_LENGTH = 2
MAX_LIMIT = 100
FALLBACK_SNIPPET_CHARS = 200


class SearchText:
    """Full-text search with a snippet from the sidecar of the best matches."""

    def __init__(self, *, uow_factory: UowFactory, storage: ObjectStorage) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage

    async def execute(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return ``[{file_id, name, snippet}]`` for matching ready files.

        An empty query lists the owner's newest ready files with an empty snippet.
        """
        query = query.strip()
        size = max(1, min(limit, MAX_LIMIT))
        if not query:
            return await self._newest(owner_id, size)
        if len(query) < MIN_QUERY_LENGTH:
            return []
        results: list[dict[str, Any]] = []
        async with self._uow_factory() as uow:
            files = await uow.files.search(owner_id, query, size)
            for file in files:
                document = (await self._storage.get(file.text_key)).decode()
                snippet = await uow.files.headline(document, query)
                results.append(
                    {
                        "file_id": file.id,
                        "name": file.name,
                        "snippet": snippet or document[:FALLBACK_SNIPPET_CHARS],
                    }
                )
        return results

    async def _newest(self, owner_id: UUID, size: int) -> list[dict[str, Any]]:
        """The owner's newest ready files, as search results without snippets."""
        async with self._uow_factory() as uow:
            files = await uow.files.list_ready(owner_id, size)
        return [{"file_id": f.id, "name": f.name, "snippet": ""} for f in files]
