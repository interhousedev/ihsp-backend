"""Public API of the knowledge module: what other modules may import."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KnowledgeHit:
    """One found entry; `score` is its rank-fusion score (higher is better)."""

    key: str
    title: str | None
    value: str
    tags: tuple[str, ...]
    score: float


class KnowledgeSearchPort(Protocol):
    """Hybrid search (meaning, trigrams and words) over the knowledge base."""

    async def search(self, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        """Up to `limit` entries that answer the query, best first."""
        ...
