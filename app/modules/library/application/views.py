"""Read models every area returns; HTTP schemas map them one to one (doc § 7.5)."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.library.domain.enums import (
    ExternalAccess,
    ItemKind,
    ItemType,
    Rights,
    ShelfState,
    UploaderRole,
)

TagSource = Literal["unilibrary", "book", "material"]


@dataclass(frozen=True, slots=True)
class SubjectView:
    """A subject chip on a card."""

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class MaterialCardView:
    """Attribution of a material ("Aziza K., 2025")."""

    uploader_name: str
    uploader_cohort: str
    uploader_role: UploaderRole


@dataclass(frozen=True, slots=True)
class BookCardView:
    """Rights line of a book."""

    rights: Rights
    licence: str | None
    download_allowed: bool


@dataclass(frozen=True, slots=True)
class ExternalCardView:
    """The UniLibrary block of a card; `view_url` is the only way to read it."""

    external_id: str
    category: int
    access: ExternalAccess
    type_name: str
    field_name: str
    view_url: str
    gone: bool
    source: Literal["unilibrary"] = "unilibrary"


@dataclass(frozen=True, slots=True)
class ItemCardView:
    """`ItemCard` of the TypeScript contract. `id` is None for an unstored record."""

    id: UUID | None
    slug: str | None
    kind: ItemKind
    type: ItemType
    title: str
    author_label: str
    language: str
    year_published: int | None
    cover_url: str | None
    description_excerpt: str | None
    subjects: tuple[SubjectView, ...]
    years_of_study: tuple[int, ...]
    has_text: bool
    page_count: int | None
    shelf_state: ShelfState | None
    progress_percent: float | None
    tag_source: TagSource
    tag_label: str
    snippet: str | None = None
    snippet_page: int | None = None
    material: MaterialCardView | None = None
    book: BookCardView | None = None
    external: ExternalCardView | None = None
