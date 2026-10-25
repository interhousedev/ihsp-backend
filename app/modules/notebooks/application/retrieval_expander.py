"""The chat retrieval with its small-model helpers: decomposition, then multi-hop."""

from app.modules.notebooks.application.multi_hop_retrieval import (
    MultiHopRetrieval,
    Search,
)
from app.modules.notebooks.application.query_decomposer import QueryDecomposer
from app.modules.notebooks.domain.entities import Passage


class RetrievalExpander:
    """Finds the hits of a chat question; both helpers are off by default."""

    def __init__(
        self, decomposer: QueryDecomposer, multi_hop: MultiHopRetrieval
    ) -> None:
        """Store the helpers."""
        self.decomposer = decomposer
        self.multi_hop = multi_hop

    async def hits(self, question: str, search: Search, limit: int) -> list[Passage]:
        """Return the passages of the sub-questions or the question, plus the gaps."""
        found = await self.decomposer.retrieve(question, search, limit)
        if found is None:
            found = await search(question, limit)
        return await self.multi_hop.expand(question, found, search)
