"""Search the owner's files by their extracted text (assistant, global search)."""

import asyncio
from typing import Any
from uuid import UUID

from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory

MIN_QUERY_LENGTH = 2
MAX_LIMIT = 20  # each hit costs one S3 read of the extracted text
FALLBACK_SNIPPET_CHARS = 200
SNIPPET_SOURCE_CHARS = 200_000  # the headline looks at this much text per hit
PARALLEL_READS = 5


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
        The extracted texts are read from storage a few at a time, not one by one.
        """
        query = query.strip()
        size = max(1, min(limit, MAX_LIMIT))
        if not query:
            return await self._newest(owner_id, size)
        if len(query) < MIN_QUERY_LENGTH:
            return []
        async with self._uow_factory() as uow:
            files = await uow.files.search(owner_id, query, size)
            documents = await self._documents(files)
            results: list[dict[str, Any]] = []
            for file, document in zip(files, documents, strict=True):
                snippet = await uow.files.headline(document, query)
                results.append(
                    {
                        "file_id": file.id,
                        "name": file.name,
                        "snippet": snippet or document[:FALLBACK_SNIPPET_CHARS],
                    }
                )
        return results

    async def _documents(self, files: list[StoredFile]) -> list[str]:
        """The start of each file's extracted text, read with bounded parallelism."""
        gate = asyncio.Semaphore(PARALLEL_READS)

        async def one(file: StoredFile) -> str:
            async with gate:
                raw = await self._storage.get(file.text_key)
            return raw.decode()[:SNIPPET_SOURCE_CHARS]

        return list(await asyncio.gather(*(one(file) for file in files)))

    async def _newest(self, owner_id: UUID, size: int) -> list[dict[str, Any]]:
        """The owner's newest ready files, as search results without snippets."""
        async with self._uow_factory() as uow:
            files = await uow.files.list_ready(owner_id, size)
        return [{"file_id": f.id, "name": f.name, "snippet": ""} for f in files]
