"""Port: the shared content layer (documents, their passages, aliases and guides)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.entities import (
    Document,
    DraftPassage,
    SourceGuide,
)


class DocumentRepository(Protocol):
    """Documents in `notebooks.documents` and what hangs on them."""

    async def find_by_hash(self, content_hash: str) -> Document | None:
        """The document of a normalized text, if one was stored."""
        ...

    async def find_by_alias(self, alias: str) -> Document | None:
        """The document a file (checksum or id) turned into, if known."""
        ...

    async def add_aliases(self, aliases: Sequence[str], document_id: UUID) -> None:
        """Remember identities of the text; an alias that exists is left alone."""
        ...

    async def create(
        self,
        content_hash: str,
        passages: Sequence[DraftPassage],
        *,
        word_count: int,
        char_count: int,
        token_estimate: int,
    ) -> Document:
        """Store a document with its passages (new UUIDv7 ids).

        If another transaction stored the same text first, that document is
        returned and nothing is inserted.
        """
        ...

    async def get_guide(self, document_id: UUID, language: str) -> SourceGuide | None:
        """The guide of the document in a language, if one was written."""
        ...

    async def save_guide(
        self, document_id: UUID, language: str, guide: SourceGuide
    ) -> None:
        """Keep the guide (the first one written for a language wins)."""
        ...

    async def delete_unused(self, created_before: datetime, limit: int) -> int:
        """Delete documents created before the cutoff that no source points at."""
        ...
