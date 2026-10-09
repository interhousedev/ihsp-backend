"""Response models of the full-text search in a notebook's sources (§ 3.3)."""

from typing import Self
from uuid import UUID

from app.modules.notebooks.application.search_sources import (
    SearchHit,
    SearchResult,
    SourceHits,
)
from app.modules.notebooks.domain.enums import SourceKind

from pydantic import BaseModel


class SearchHitResponse(BaseModel):
    """`SearchHit`: a passage that matches."""

    passage_id: UUID
    seq: int
    page: int | None
    snippet: str
    """About 200 characters of plain text around the first match; no markup."""

    @classmethod
    def from_hit(cls, hit: SearchHit) -> Self:
        """Build from the use case hit."""
        return cls(
            passage_id=hit.passage_id, seq=hit.seq, page=hit.page, snippet=hit.snippet
        )


class SearchSourceResponse(BaseModel):
    """`SearchSource`: a source and its best passages (at most 3)."""

    source_id: UUID
    title: str
    kind: SourceKind
    hits: list[SearchHitResponse]

    @classmethod
    def from_hits(cls, found: SourceHits) -> Self:
        """Build from the use case group."""
        return cls(
            source_id=found.source_id,
            title=found.title,
            kind=found.kind,
            hits=[SearchHitResponse.from_hit(h) for h in found.hits],
        )


class SearchResponse(BaseModel):
    """`SearchResults`: the request as searched and the sources with hits."""

    query: str
    sources: list[SearchSourceResponse]
    """Best hit first."""

    @classmethod
    def from_result(cls, result: SearchResult) -> Self:
        """Build from the use case result."""
        return cls(
            query=result.query,
            sources=[SearchSourceResponse.from_hits(s) for s in result.sources],
        )
