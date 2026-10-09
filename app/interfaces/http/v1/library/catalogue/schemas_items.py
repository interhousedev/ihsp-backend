"""`ItemCard` and `ItemDetail` of the TypeScript contract (doc § 7.5).

Every area that answers with items imports `ItemCardSchema.from_view(card)` and
`ItemDetailSchema.from_view(view)` from here. Keys the contract marks optional
(`material`, `book`, `external`, `rights_box`, ...) are left out of the JSON when
they do not apply; nullable keys stay as `null`.
"""

from typing import Literal, Self
from uuid import UUID

from app.modules.library.application.detail import (
    CanView,
    ItemDetailView,
    ItemFileView,
    ListRefView,
    RightsBoxView,
    TopicRefView,
)
from app.modules.library.application.views import (
    BookCardView,
    ExternalCardView,
    ItemCardView,
    MaterialCardView,
    SubjectView,
    TagSource,
)
from app.modules.library.domain.enums import (
    ExternalAccess,
    FileFormat,
    Importance,
    ItemKind,
    ItemStatus,
    ItemType,
    Rights,
    ShelfState,
    StatusReasonCode,
    TextStatus,
    UploaderRole,
    Visibility,
)

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer

# Keys of the contract that are `key?:` (absent, never `null`).
_OPTIONAL_KEYS = frozenset(
    {
        "material",
        "book",
        "external",
        "rights_box",
        "external_keywords",
        "external_isbn",
    }
)


class SubjectRefSchema(BaseModel):
    """`{id, name}` subject chip."""

    id: UUID
    name: str

    @classmethod
    def from_view(cls, view: SubjectView) -> Self:
        """Build from the subject view."""
        return cls(id=view.id, name=view.name)


class ItemTagSchema(BaseModel):
    """The source tag of a card."""

    source: TagSource
    label: str


class MaterialBlockSchema(BaseModel):
    """`material` block of a card: the uploader attribution."""

    uploader_name: str
    uploader_cohort: str
    uploader_role: UploaderRole

    @classmethod
    def from_view(cls, view: MaterialCardView) -> Self:
        """Build from the material view."""
        return cls(
            uploader_name=view.uploader_name,
            uploader_cohort=view.uploader_cohort,
            uploader_role=view.uploader_role,
        )


class BookBlockSchema(BaseModel):
    """`book` block of a card: the rights line."""

    rights: Rights
    licence: str | None
    download_allowed: bool

    @classmethod
    def from_view(cls, view: BookCardView) -> Self:
        """Build from the book view."""
        return cls(
            rights=view.rights,
            licence=view.licence,
            download_allowed=view.download_allowed,
        )


class ExternalBlockSchema(BaseModel):
    """`external` block of a card: the UniLibrary record."""

    source: Literal["unilibrary"]
    external_id: str
    category: Literal[1, 2, 3, 4]
    access: ExternalAccess
    type_name: str
    field_name: str
    view_url: str
    gone: bool

    @classmethod
    def from_view(cls, view: ExternalCardView) -> Self:
        """Build from the external view."""
        return cls.model_validate(
            {
                "source": view.source,
                "external_id": view.external_id,
                "category": view.category,
                "access": view.access,
                "type_name": view.type_name,
                "field_name": view.field_name,
                "view_url": view.view_url,
                "gone": view.gone,
            }
        )


class ItemCardBase(BaseModel):
    """The fields of `ItemCard`, shared by the card and the detail."""

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
    subjects: list[SubjectRefSchema]
    years_of_study: list[int]
    has_text: bool
    page_count: int | None
    shelf_state: ShelfState | None
    progress_percent: float | None
    snippet: str | None
    snippet_page: int | None
    tag: ItemTagSchema
    material: MaterialBlockSchema | None = None
    book: BookBlockSchema | None = None
    external: ExternalBlockSchema | None = None

    @model_serializer(mode="wrap")
    def _drop_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Leave out the optional keys that do not apply to this item."""
        data: dict[str, object] = handler(self)
        return {
            k: v for k, v in data.items() if k not in _OPTIONAL_KEYS or v is not None
        }

    @staticmethod
    def card_fields(view: ItemCardView) -> dict[str, object]:
        """Constructor arguments of the card part (shared with the detail)."""
        return {
            "id": view.id,
            "slug": view.slug,
            "kind": view.kind,
            "type": view.type,
            "title": view.title,
            "author_label": view.author_label,
            "language": view.language,
            "year_published": view.year_published,
            "cover_url": view.cover_url,
            "description_excerpt": view.description_excerpt,
            "subjects": [SubjectRefSchema.from_view(s) for s in view.subjects],
            "years_of_study": list(view.years_of_study),
            "has_text": view.has_text,
            "page_count": view.page_count,
            "shelf_state": view.shelf_state,
            "progress_percent": view.progress_percent,
            "snippet": view.snippet,
            "snippet_page": view.snippet_page,
            "tag": ItemTagSchema(source=view.tag_source, label=view.tag_label),
            "material": (
                MaterialBlockSchema.from_view(view.material) if view.material else None
            ),
            "book": BookBlockSchema.from_view(view.book) if view.book else None,
            "external": (
                ExternalBlockSchema.from_view(view.external) if view.external else None
            ),
        }


class ItemCardSchema(ItemCardBase):
    """`ItemCard`."""

    @classmethod
    def from_view(cls, view: ItemCardView) -> Self:
        """Build from the card read model."""
        return cls.model_validate(cls.card_fields(view))


class TocEntrySchema(BaseModel):
    """`TocEntry`: `page` for PDF, `href` for EPUB."""

    title: str
    level: int
    page: int | None = None
    href: str | None = None

    @model_serializer(mode="wrap")
    def _drop_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Leave out `page` or `href` when the entry has none."""
        data: dict[str, object] = handler(self)
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, entry: dict[str, object]) -> Self:
        """Build from a stored outline entry (extra keys are ignored)."""
        page = entry.get("page")
        href = entry.get("href")
        level = entry.get("level")
        return cls(
            title=str(entry.get("title", "")),
            level=level if isinstance(level, int) else 1,
            page=page if isinstance(page, int) else None,
            href=href if isinstance(href, str) else None,
        )


class ItemFileSchema(BaseModel):
    """`ItemFile` of the contract."""

    id: UUID
    format: FileFormat
    is_primary: bool
    pages: int | None
    byte_size: int
    readable: bool
    text_status: TextStatus
    toc: list[TocEntrySchema]

    @classmethod
    def from_view(cls, view: ItemFileView) -> Self:
        """Build from the file view."""
        return cls(
            id=view.id,
            format=view.format,
            is_primary=view.is_primary,
            pages=view.pages,
            byte_size=view.byte_size,
            readable=view.readable,
            text_status=view.text_status,
            toc=[TocEntrySchema.from_dict(entry) for entry in view.toc],
        )


class TopicRefSchema(BaseModel):
    """A topic the item feeds, with the page range."""

    id: UUID
    name: str
    page_from: int | None
    page_to: int | None

    @classmethod
    def from_view(cls, view: TopicRefView) -> Self:
        """Build from the topic view."""
        return cls(
            id=view.id, name=view.name, page_from=view.page_from, page_to=view.page_to
        )


class ListRefSchema(BaseModel):
    """A reading list the item is on."""

    id: UUID
    title: str
    importance: Importance

    @classmethod
    def from_view(cls, view: ListRefView) -> Self:
        """Build from the list view."""
        return cls(id=view.id, title=view.title, importance=view.importance)


class RightsBoxSchema(BaseModel):
    """The rights statement of a book page."""

    text: str
    attribution: str | None
    download_allowed: bool

    @classmethod
    def from_view(cls, view: RightsBoxView) -> Self:
        """Build from the rights box view."""
        return cls(
            text=view.text,
            attribution=view.attribution,
            download_allowed=view.download_allowed,
        )


class CanSchema(BaseModel):
    """What the caller may do with the item."""

    read: bool
    download: bool
    add_to_notebook: bool
    report: bool
    edit: bool

    @classmethod
    def from_view(cls, view: CanView) -> Self:
        """Build from the permission view."""
        return cls(
            read=view.read,
            download=view.download,
            add_to_notebook=view.add_to_notebook,
            report=view.report,
            edit=view.edit,
        )


class ItemDetailSchema(ItemCardBase):
    """`ItemDetail`: the card plus status, files, topics and lists."""

    status: ItemStatus
    status_reason: StatusReasonCode | str | None
    status_note: str | None
    visibility: Visibility
    subtitle: str | None
    description: str | None
    publisher: str | None
    isbn: str | None
    files: list[ItemFileSchema]
    topics: list[TopicRefSchema]
    lists: list[ListRefSchema]
    can: CanSchema
    rights_box: RightsBoxSchema | None = None
    external_keywords: list[str] | None = None
    external_isbn: str | None = None

    @classmethod
    def from_view(cls, view: ItemDetailView) -> Self:
        """Build from the detail read model."""
        return cls.model_validate(
            {
                **cls.card_fields(view.card),
                "status": view.status,
                "status_reason": view.status_reason,
                "status_note": view.status_note,
                "visibility": view.visibility,
                "subtitle": view.subtitle,
                "description": view.description,
                "publisher": view.publisher,
                "isbn": view.isbn,
                "files": [ItemFileSchema.from_view(f) for f in view.files],
                "topics": [TopicRefSchema.from_view(t) for t in view.topics],
                "lists": [ListRefSchema.from_view(x) for x in view.lists],
                "can": CanSchema.from_view(view.can),
                "rights_box": (
                    RightsBoxSchema.from_view(view.rights_box)
                    if view.rights_box
                    else None
                ),
                "external_keywords": (
                    list(view.external_keywords)
                    if view.external_keywords is not None
                    else None
                ),
                "external_isbn": view.external_isbn,
            }
        )
