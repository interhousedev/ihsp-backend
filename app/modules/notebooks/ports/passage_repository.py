"""Port: storage and lexical search of passages."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.entities import Passage
from app.shared.contracts.embeddings import QueryVector, TextToEmbed


class PassageRepository(Protocol):
    """Reads passages through the sources that hold their document.

    A source whose text is shared with other notebooks reads the same passages; each
    passage is returned with the id and notebook of the source it was asked through.
    The passages themselves are stored by `DocumentRepository`.
    """

    async def get(self, passage_id: UUID, notebook_id: UUID) -> Passage | None:
        """One passage of the notebook; None when no source of it holds the passage."""
        ...

    async def get_many(
        self, passage_ids: Sequence[UUID], notebook_id: UUID
    ) -> list[Passage]:
        """The notebook's passages among the ids (any order)."""
        ...

    async def list_for_source(
        self, source_id: UUID, *, after_seq: int, limit: int
    ) -> list[Passage]:
        """Passages with `seq > after_seq`, ascending."""
        ...

    async def list_for_sources(self, source_ids: Sequence[UUID]) -> list[Passage]:
        """All passages of the sources, ordered by the given source order then `seq`."""
        ...

    async def neighbours(
        self, source_id: UUID, seq: int, context: int
    ) -> tuple[list[Passage], list[Passage]]:
        """Passages `seq-context..seq-1` and `seq+1..seq+context` (ascending)."""
        ...

    async def search(
        self,
        notebook_id: UUID,
        source_ids: Sequence[UUID],
        query: str,
        limit: int,
        *,
        query_vector: QueryVector | None = None,
    ) -> list[Passage]:
        """Rank the passages of the sources for a query, best first.

        Lexical: full-text rank over the `russian` and `simple` vectors with prefix
        terms for Uzbek word endings ("fotosintezda" finds "fotosintez"); passages
        without any matching word are not returned.

        With a `query_vector` the ranking is hybrid: the lexical ranking and the
        cosine ranking over the stored passage vectors of the same model are fused
        by reciprocal rank fusion, so a passage that shares no word with the
        question (another language or script, a paraphrase) can still be found.
        Passages that have no vector yet take part through the lexical ranking
        only; when none of them has a vector the result is the lexical one.
        """
        ...

    async def missing_embeddings(
        self, model: str, limit: int, *, document_id: UUID | None = None
    ) -> list[TextToEmbed]:
        """Distinct passage texts that have no vector of `model`, by content hash.

        Limited to the passages of one document when `document_id` is given.
        """
        ...
