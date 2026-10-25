"""Port: web pages the search found, and the queries it answered, kept in the database.

The vector of a page is the vector of its text in `vectors.embeddings` (by content
hash); `nearest` compares a question with those vectors, so the store needs no vector
of its own.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PageRecord:
    """A page as one search returned it; `url` is already normalised."""

    url: str
    site: str
    title: str
    text: str
    highlight: str
    published_date: date | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class StoredPage:
    """A page as it is kept."""

    id: UUID
    url: str
    site: str
    title: str
    text: str
    highlight: str
    published_date: date | None


class WebPageStore(Protocol):
    """`ai.web_pages` and `ai.web_queries`; each method is one statement or a batch."""

    async def upsert(
        self, pages: Sequence[PageRecord], now: datetime
    ) -> dict[str, UUID]:
        """Store new pages and refresh known ones (`last_seen_at`, `times_returned`).

        Returns the id of each URL.
        """
        ...

    async def pages(self, ids: Sequence[UUID]) -> list[StoredPage]:
        """The stored pages of the ids, in their order (missing ones are skipped)."""
        ...

    async def nearest(
        self, model: str, values: Sequence[float], limit: int, min_similarity: float
    ) -> list[tuple[UUID, float]]:
        """Pages whose vector of `model` is close enough to the question.

        Best first, with their similarity (cosine, 0 to 1); at least `min_similarity`.
        """
        ...

    async def cached(self, cache_key: str, since: datetime) -> list[UUID] | None:
        """The ordered page ids of a query answered at or after `since`; None if not."""
        ...

    async def put_query(
        self, cache_key: str, query: str, ids: Sequence[UUID], now: datetime
    ) -> None:
        """Remember the ordered page ids of a query (replaces an older answer)."""
        ...

    async def purge_pages(self, cutoff: datetime, limit: int) -> tuple[int, int]:
        """Delete up to `limit` pages last seen before `cutoff`, and unused vectors.

        Returns (pages deleted, vectors deleted).
        """
        ...

    async def purge_queries(self, cutoff: datetime, limit: int) -> int:
        """Delete up to `limit` cached queries answered before `cutoff`."""
        ...
