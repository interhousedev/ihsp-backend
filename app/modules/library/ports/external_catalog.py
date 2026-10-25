"""Port: an external catalogue (UniLibrary) read over HTTP, metadata only."""

from dataclasses import dataclass, field
from typing import Protocol

from app.modules.library.domain.enums import (
    ExternalAccess,
    ItemLanguage,
    ItemType,
)


@dataclass(frozen=True, slots=True)
class ExternalRecord:
    """One record of the external catalogue, as facts (never a file)."""

    external_id: str
    category: int  # 1 literature, 2 monograph, 3 dissertation, 4 article
    title: str
    authors: str
    access: ExternalAccess
    view_url: str
    item_type: ItemType
    language: ItemLanguage
    year: int | None = None
    publisher: str | None = None
    type_id: int | None = None
    type_name: str | None = None
    field_id: int | None = None
    field_name: str | None = None
    language_id: int | None = None
    language_name: str | None = None
    description: str | None = None
    cover_url: str | None = None
    views: int = 0
    # Only the detail response has these.
    keywords: tuple[str, ...] | None = None
    isbn: str | None = None
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class ExternalSearch:
    """What a search asks for; unset filters are not sent."""

    q: str | None = None
    page: int = 1
    limit: int = 20
    language: str = "uz"  # language of the names in the answer
    category: int = 1
    field_id: int | None = None
    type_id: int | None = None
    language_id: int | None = None
    access: ExternalAccess | None = None


@dataclass(frozen=True, slots=True)
class ExternalPage:
    """A page of records; `stale` when the cache answered because of a failure."""

    records: tuple[ExternalRecord, ...]
    page: int
    last_page: int
    total: int
    stale: bool = False


@dataclass(frozen=True, slots=True)
class TaxonomyEntry:
    """A type, field or language of the external catalogue."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ExternalTaxonomies:
    """The filters the search can use, names in one language."""

    types: tuple[TaxonomyEntry, ...] = field(default_factory=tuple)
    fields: tuple[TaxonomyEntry, ...] = field(default_factory=tuple)
    languages: tuple[TaxonomyEntry, ...] = field(default_factory=tuple)
    stale: bool = False


class ExternalCatalog(Protocol):
    """Reads the external catalogue; raises `ExternalUnavailableError` on failure.

    There is deliberately no method for files or storage URLs (link-only, D3).
    """

    async def search(self, params: ExternalSearch) -> ExternalPage:
        """A page of records matching the search."""
        ...

    async def get(
        self, external_id: str, *, category: int, language: str
    ) -> tuple[ExternalRecord | None, bool]:
        """The full record (None when the catalogue no longer has it) and `stale`."""
        ...

    async def taxonomies(self, language: str) -> ExternalTaxonomies:
        """Types, fields and languages for the search filters."""
        ...
