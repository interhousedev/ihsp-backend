"""Requests and responses of the catalogue endpoints (names follow doc § 7.5)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import (
    ItemCardSchema,
    ItemDetailSchema,
)
from app.modules.library.application.catalogue.books.get_book_draft import (
    BookDraftView,
)
from app.modules.library.application.catalogue.books.import_books import (
    ImportResultView,
)
from app.modules.library.application.catalogue.books.list_books import BookRowView
from app.modules.library.application.catalogue.get_file_url import FileUrlView
from app.modules.library.application.catalogue.get_item_text import TextPageView
from app.modules.library.application.catalogue.list_subjects import SubjectCountView
from app.modules.library.domain.catalogue_books import BookData
from app.modules.library.domain.catalogue_search import ItemSort, ItemSource
from app.modules.library.domain.entities import SubjectLink, TopicLink
from app.modules.library.domain.enums import (
    FileFormat,
    ItemLanguage,
    ItemStatus,
    ItemType,
    Rights,
    ShelfState,
    SubjectRole,
    TextStatus,
    Visibility,
)
from app.modules.library.domain.rights import ChecklistEntry

from pydantic import BaseModel, Field, model_validator

# - - - Query of the list - - -


class ItemsParams(BaseModel):
    """`GET /library/items` query string."""

    q: str | None = Field(default=None, max_length=200)
    source: ItemSource = ItemSource.ALL
    subject_id: UUID | None = None
    topic_id: UUID | None = None
    tag: str | None = Field(default=None, max_length=40)
    year_of_study: int | None = Field(default=None, ge=1, le=12)
    type: ItemType | None = None
    language: str | None = Field(default=None, max_length=10)
    collection_id: UUID | None = None
    uploader_role: Literal["student", "teacher"] | None = None
    has_text: bool | None = None
    shelf: ShelfState | Literal["any"] | None = None
    sort: ItemSort = ItemSort.RELEVANCE
    cursor: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)


# - - - Reading - - -


class FileUrlSchema(BaseModel):
    """`ItemFileUrl`: a presigned URL valid for 15 minutes."""

    url: str
    expires_at: datetime
    content_type: str
    byte_size: int

    @classmethod
    def from_view(cls, view: FileUrlView) -> Self:
        """Build from the use case result."""
        return cls(
            url=view.url,
            expires_at=view.expires_at,
            content_type=view.content_type,
            byte_size=view.byte_size,
        )


class TextPageSchema(BaseModel):
    """One page of extracted text."""

    page: int
    text: str


class ItemTextSchema(BaseModel):
    """`ItemText`."""

    pages: list[TextPageSchema]

    @classmethod
    def from_views(cls, pages: list[TextPageView]) -> Self:
        """Build from the pages of the use case."""
        return cls(pages=[TextPageSchema(page=p.page, text=p.text) for p in pages])


class LibrarySubjectSchema(BaseModel):
    """`LibrarySubject`: a subject with its number of visible items."""

    id: UUID
    name: str
    item_count: int
    parent_id: UUID | None = None
    code: str | None = None

    @classmethod
    def from_view(cls, view: SubjectCountView) -> Self:
        """Build from the use case result."""
        return cls(
            id=view.id,
            name=view.name,
            item_count=view.item_count,
            parent_id=view.parent_id,
            code=view.code,
        )


class TagSuggestionSchema(BaseModel):
    """`TagSuggestion`: an existing tag and how many published items carry it."""

    name: str
    item_count: int


# - - - Book input - - -


class RightsBasisSchema(BaseModel):
    """`RightsBasis`: the fields used depend on the rights class."""

    author_death_year: int | None = None
    first_published_year: int | None = None
    rule: str | None = Field(default=None, max_length=60)
    source_url: str | None = Field(default=None, max_length=500)
    attribution: str | None = Field(default=None, max_length=500)
    permission_scope: str | None = Field(default=None, max_length=300)
    permission_expires_on: str | None = Field(default=None, max_length=10)
    reference: str | None = Field(default=None, max_length=500)

    def to_basis(self) -> dict[str, object]:
        """The recorded facts without the empty ones."""
        return {k: v for k, v in self.model_dump().items() if v not in (None, "")}


class BookSubjectInput(BaseModel):
    """A subject of the book with its role and optional year of study."""

    subject_id: UUID
    role: SubjectRole
    year_of_study: int | None = Field(default=None, ge=1, le=12)

    def to_link(self) -> SubjectLink:
        """The domain tag."""
        return SubjectLink(self.subject_id, self.role, self.year_of_study)


class BookTopicInput(BaseModel):
    """A topic the book feeds, with an optional chapter range."""

    topic_id: UUID
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)

    def to_link(self, position: int) -> TopicLink:
        """The domain tag."""
        return TopicLink(self.topic_id, self.page_from, self.page_to, position)


class BookInputBody(BaseModel):
    """`BookInput`: the book form (POST) and the editor's saved data (GET draft)."""

    title: str = Field(min_length=1, max_length=255)
    subtitle: str | None = Field(default=None, max_length=255)
    authors: list[str] = Field(max_length=20)
    translators: list[str] = Field(default_factory=list, max_length=20)
    language: ItemLanguage
    year_published: int | None = Field(default=None, ge=-3000, le=2200)
    publisher: str | None = Field(default=None, max_length=255)
    isbn: str | None = Field(default=None, max_length=32)
    type: ItemType
    description: str | None = Field(default=None, max_length=2000)
    years_of_study: list[int] = Field(max_length=4)
    subjects: list[BookSubjectInput] = Field(max_length=20)
    topics: list[BookTopicInput] = Field(max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    rights: Rights = Rights.OFFICIAL
    licence: str | None = Field(default=None, max_length=40)
    rights_basis: RightsBasisSchema = Field(default_factory=RightsBasisSchema)
    rights_proof_file_id: UUID | None = None
    cover_file_id: UUID | None = None
    visibility: Visibility
    download_allowed: bool

    def to_data(self) -> BookData:
        """The domain form data."""
        return BookData(
            title=self.title,
            subtitle=self.subtitle,
            authors=self.authors,
            translators=self.translators,
            language=self.language,
            year_published=self.year_published,
            publisher=self.publisher,
            isbn=self.isbn,
            type=self.type,
            description=self.description,
            years_of_study=self.years_of_study,
            subjects=[s.to_link() for s in self.subjects],
            topics=[t.to_link(i) for i, t in enumerate(self.topics)],
            tags=self.tags,
            rights=self.rights,
            licence=self.licence,
            rights_basis=self.rights_basis.to_basis(),
            rights_proof_file_id=self.rights_proof_file_id,
            cover_file_id=self.cover_file_id,
            visibility=self.visibility,
            download_allowed=self.download_allowed,
        )

    @classmethod
    def from_data(cls, data: BookData) -> Self:
        """Build from the stored form data (the editor)."""
        return cls(
            title=data.title,
            subtitle=data.subtitle,
            authors=list(data.authors),
            translators=list(data.translators),
            language=data.language,
            year_published=data.year_published,
            publisher=data.publisher,
            isbn=data.isbn,
            type=data.type,
            description=data.description,
            years_of_study=list(data.years_of_study),
            subjects=[
                BookSubjectInput(
                    subject_id=s.subject_id, role=s.role, year_of_study=s.year_of_study
                )
                for s in data.subjects
            ],
            topics=[
                BookTopicInput(
                    topic_id=t.topic_id, page_from=t.page_from, page_to=t.page_to
                )
                for t in data.topics
            ],
            tags=list(data.tags),
            rights=data.rights,
            licence=data.licence,
            rights_basis=_basis_schema(data.rights_basis),
            rights_proof_file_id=data.rights_proof_file_id,
            cover_file_id=data.cover_file_id,
            visibility=data.visibility,
            download_allowed=data.download_allowed,
        )


def _basis_schema(basis: dict[str, object]) -> RightsBasisSchema:
    known = RightsBasisSchema.model_fields
    return RightsBasisSchema.model_validate(
        {k: v for k, v in basis.items() if k in known}
    )


NOT_NULLABLE = frozenset(
    {
        "title",
        "authors",
        "translators",
        "language",
        "type",
        "years_of_study",
        "subjects",
        "topics",
        "tags",
        "rights",
        "rights_basis",
        "visibility",
        "download_allowed",
    }
)


class BookPatchBody(BaseModel):
    """`PATCH /manage/library/books/{id}`: only the keys that were sent change."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    subtitle: str | None = Field(default=None, max_length=255)
    authors: list[str] | None = Field(default=None, max_length=20)
    translators: list[str] | None = Field(default=None, max_length=20)
    language: ItemLanguage | None = None
    year_published: int | None = Field(default=None, ge=-3000, le=2200)
    publisher: str | None = Field(default=None, max_length=255)
    isbn: str | None = Field(default=None, max_length=32)
    type: ItemType | None = None
    description: str | None = Field(default=None, max_length=2000)
    years_of_study: list[int] | None = Field(default=None, max_length=4)
    subjects: list[BookSubjectInput] | None = Field(default=None, max_length=20)
    topics: list[BookTopicInput] | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=20)
    rights: Rights | None = None
    licence: str | None = Field(default=None, max_length=40)
    rights_basis: RightsBasisSchema | None = None
    rights_proof_file_id: UUID | None = None
    cover_file_id: UUID | None = None
    visibility: Visibility | None = None
    download_allowed: bool | None = None

    @model_validator(mode="after")
    def _no_null_for_required(self) -> Self:
        for name in self.model_fields_set & NOT_NULLABLE:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def to_changes(self) -> dict[str, object]:
        """Sent fields as domain values (tags become domain tags)."""
        changes: dict[str, object] = {}
        for name in self.model_fields_set:
            value = getattr(self, name)
            if name == "subjects" and value is not None:
                value = [s.to_link() for s in value]
            elif name == "topics" and value is not None:
                value = [t.to_link(i) for i, t in enumerate(value)]
            elif name == "rights_basis" and value is not None:
                value = value.to_basis()
            changes[name] = value
        return changes


class BookActionBody(BaseModel):
    """`{reason?}` of unpublish and takedown (a reason is required for takedown)."""

    reason: str | None = Field(default=None, max_length=1000)


class BookFileBody(BaseModel):
    """`POST /manage/library/books/{id}/files`."""

    file_id: UUID
    format: FileFormat
    is_primary: bool = False


class ImportBody(BaseModel):
    """`POST /manage/library/import`: the CSV is uploaded first."""

    csv_file_id: UUID


# - - - Book responses - - -


class ChecklistEntrySchema(BaseModel):
    """One check of the publish checklist."""

    key: str
    ok: bool

    @classmethod
    def from_entry(cls, entry: ChecklistEntry) -> Self:
        """Build from the domain entry."""
        return cls(key=entry.key, ok=entry.ok)


class BookDraftSchema(BaseModel):
    """`BookDraft`: the detail, the saved input and the publish checklist."""

    item: ItemDetailSchema
    input: BookInputBody
    checklist: list[ChecklistEntrySchema]

    @classmethod
    def from_view(cls, view: BookDraftView) -> Self:
        """Build from the use case result."""
        return cls(
            item=ItemDetailSchema.from_view(view.item),
            input=BookInputBody.from_data(view.data),
            checklist=[ChecklistEntrySchema.from_entry(e) for e in view.checklist],
        )


class BookRowSchema(BaseModel):
    """`BookRow`: a line of the librarian's book table."""

    item: ItemCardSchema
    status: ItemStatus
    visibility: Visibility
    rights: Rights
    text_status: TextStatus
    updated_at: datetime

    @classmethod
    def from_view(cls, view: BookRowView) -> Self:
        """Build from the use case row."""
        return cls(
            item=ItemCardSchema.from_view(view.card),
            status=view.status,
            visibility=view.visibility,
            rights=view.rights,
            text_status=view.text_status,
            updated_at=view.updated_at,
        )


class ImportErrorSchema(BaseModel):
    """A row of the CSV that was not imported."""

    row: int
    message: str


class ImportResultSchema(BaseModel):
    """`ImportResult`."""

    created: int
    errors: list[ImportErrorSchema]

    @classmethod
    def from_view(cls, view: ImportResultView) -> Self:
        """Build from the use case result."""
        return cls(
            created=view.created,
            errors=[
                ImportErrorSchema(row=e.row, message=e.message) for e in view.errors
            ],
        )
