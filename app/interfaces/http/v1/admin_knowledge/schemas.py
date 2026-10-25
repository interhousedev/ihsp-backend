"""Request and response bodies of the knowledge admin routes."""

from datetime import datetime
from uuid import UUID

from app.modules.knowledge.application.search_entries import ScoredEntry
from app.modules.knowledge.domain.entry import (
    MAX_KEY,
    MAX_TAGS,
    MAX_TITLE,
    MAX_VALUE,
    KnowledgeEntry,
)

from pydantic import BaseModel, Field


class KnowledgeEntryInput(BaseModel):
    """Body of POST /v1/admin/knowledge."""

    key: str = Field(min_length=1, max_length=MAX_KEY)
    title: str | None = Field(default=None, max_length=MAX_TITLE)
    value: str = Field(min_length=1, max_length=MAX_VALUE)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    accessible_to_guest: bool = False
    accessible_to_student: bool = True


class KnowledgeEntryPatch(BaseModel):
    """Body of PATCH /v1/admin/knowledge/{entry_id}: only the sent fields change."""

    key: str | None = Field(default=None, min_length=1, max_length=MAX_KEY)
    title: str | None = Field(default=None, max_length=MAX_TITLE)
    value: str | None = Field(default=None, min_length=1, max_length=MAX_VALUE)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    accessible_to_guest: bool | None = None
    accessible_to_student: bool | None = None


class KnowledgeEntryResponse(BaseModel):
    """KnowledgeEntry; `score` is set only for a search (`q`)."""

    id: UUID
    key: str
    title: str | None
    value: str
    tags: list[str]
    author_id: UUID
    created_at: datetime
    updated_at: datetime
    accessible_to_guest: bool
    accessible_to_student: bool
    score: float | None = None

    @classmethod
    def from_domain(
        cls, entry: KnowledgeEntry, score: float | None = None
    ) -> "KnowledgeEntryResponse":
        """Map an entry."""
        return cls(
            id=entry.id,
            key=entry.key,
            title=entry.title,
            value=entry.value,
            tags=list(entry.tags),
            author_id=entry.author_id,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            accessible_to_guest=entry.accessible_to_guest,
            accessible_to_student=entry.accessible_to_student,
            score=score,
        )


class KnowledgeEntryListResponse(BaseModel):
    """A page of entries and the total count."""

    items: list[KnowledgeEntryResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(
        cls,
        items: list[ScoredEntry],
        total: int,
        limit: int,
        offset: int,
        *,
        found: bool,
    ) -> "KnowledgeEntryListResponse":
        """Map a page; scores are shown only when it came from a search."""
        return cls(
            items=[
                KnowledgeEntryResponse.from_domain(i.entry, i.score if found else None)
                for i in items
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
