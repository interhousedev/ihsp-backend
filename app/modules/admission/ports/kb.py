"""Storage of the FAQ knowledge base."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.kb import Article


class KbRepository(Protocol):
    """FAQ articles; search is full text over title and body."""

    async def get(self, article_id: UUID) -> Article | None:
        """One article or None."""
        ...

    async def search(
        self,
        *,
        query: str | None,
        locale: str | None,
        tag: str | None,
        status: str | None,
        limit: int,
    ) -> list[Article]:
        """Matching articles, best match first (newest first without a query)."""
        ...

    async def add(self, article: Article) -> None:
        """Store a new article."""
        ...

    async def save(self, article: Article) -> None:
        """Overwrite an article's fields."""
        ...

    async def delete(self, article_id: UUID) -> bool:
        """Delete an article; False when it did not exist."""
        ...
