"""`KnowledgeSearchPort` implementation over the hybrid search."""

from app.modules.knowledge.application.public_api import KnowledgeHit
from app.modules.knowledge.application.search_entries import SearchEntries


class KnowledgeSearch:
    """What other modules (the assistant) call to look facts up."""

    def __init__(self, *, search: SearchEntries, default_limit: int) -> None:
        """Store the use case and the default limit."""
        self._search = search
        self._default_limit = default_limit

    async def search(self, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        """Up to `limit` hits, best first."""
        found = await self._search.execute(query, limit=limit or self._default_limit)
        return [
            KnowledgeHit(
                key=item.entry.key,
                title=item.entry.title,
                value=item.entry.value,
                tags=tuple(item.entry.tags),
                score=item.score,
            )
            for item in found
        ]
