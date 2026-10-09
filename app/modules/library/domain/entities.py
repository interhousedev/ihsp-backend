"""Domain entities every area of the library shares: the item and its parts."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.library.domain.enums import (
    Approval,
    EventKind,
    ExternalAccess,
    ExternalSource,
    FileFormat,
    ItemKind,
    ItemLanguage,
    ItemStatus,
    ItemType,
    MaterialLicence,
    Rights,
    SubjectRole,
    TextStatus,
    UploaderRole,
    Visibility,
)


@dataclass(slots=True)
class ItemFile:
    """A file of a book or a material (bytes live in the files module)."""

    item_id: UUID
    file_id: UUID
    format: FileFormat
    byte_size: int
    is_primary: bool = False
    pages: int | None = None
    readable: bool = True
    text_status: TextStatus = TextStatus.NONE
    toc: list[dict[str, Any]] = field(default_factory=list)
    sha256: str | None = None


@dataclass(slots=True)
class ExternalDetails:
    """The facts read from an external (UniLibrary) record, as a snapshot."""

    source: ExternalSource
    external_id: str
    category: int
    access: ExternalAccess
    view_url: str
    snapshot_hash: str
    fetched_at: datetime
    type_name: dict[str, str] = field(default_factory=dict)
    field_name: dict[str, str] = field(default_factory=dict)
    language_name: dict[str, str] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)
    feed_id: UUID | None = None
    detail_fetched_at: datetime | None = None
    gone_at: datetime | None = None


@dataclass(slots=True)
class BookDetails:
    """Rights class and recorded basis of a hosted book (LIB-3)."""

    rights: Rights
    licence: str | None = None
    rights_basis: dict[str, Any] = field(default_factory=dict)
    rights_proof_file_id: UUID | None = None
    rights_checked_by: UUID | None = None
    rights_checked_at: datetime | None = None
    translators: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MaterialDetails:
    """Uploader snapshot, licence, approval and scan findings of a material."""

    uploader_id: UUID
    uploader_role: UploaderRole
    uploader_name: str
    licence: MaterialLicence
    uploader_cohort: str = ""
    attested_at: datetime | None = None
    approval: Approval | None = None
    submitted_at: datetime | None = None
    review_message: str | None = None
    scan: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Item:
    """A catalogue item of any kind with the details of its kind and its files.

    Exactly one of `external`, `book`, `material` is set, matching `kind`.
    """

    id: UUID
    slug: str
    kind: ItemKind
    type: ItemType
    title: str
    language: ItemLanguage
    status: ItemStatus
    visibility: Visibility
    created_at: datetime
    updated_at: datetime
    title_alt: dict[str, str] = field(default_factory=dict)
    subtitle: str | None = None
    authors: list[str] = field(default_factory=list)
    author_label: str = ""
    year_published: int | None = None
    publisher: str | None = None
    isbn: str | None = None
    description: str | None = None
    cover_file_id: UUID | None = None
    cover_url: str | None = None
    years_of_study: list[int] = field(default_factory=list)
    status_reason: str | None = None
    status_note: str | None = None
    download_allowed: bool = False
    has_text: bool = False
    page_count: int | None = None
    search_text: str = ""
    content_hash: str | None = None
    owner_id: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    supersedes_id: UUID | None = None
    open_reports: int = 0
    created_by: UUID | None = None
    external: ExternalDetails | None = None
    book: BookDetails | None = None
    material: MaterialDetails | None = None
    files: list[ItemFile] = field(default_factory=list)

    @property
    def primary_file(self) -> ItemFile | None:
        """The file the reader opens first: the primary one, else the first."""
        for item_file in self.files:
            if item_file.is_primary:
                return item_file
        return self.files[0] if self.files else None

    def file(self, file_id: UUID) -> ItemFile | None:
        """The file with this id, or None."""
        for item_file in self.files:
            if item_file.file_id == file_id:
                return item_file
        return None


@dataclass(frozen=True, slots=True)
class SubjectLink:
    """An item belongs to a subject (`year_of_study` None means any year)."""

    subject_id: UUID
    role: SubjectRole = SubjectRole.SUPPLEMENTARY
    year_of_study: int | None = None


@dataclass(frozen=True, slots=True)
class TopicLink:
    """An item (or a page range of it) feeds a topic."""

    topic_id: UUID
    page_from: int | None = None
    page_to: int | None = None
    position: int = 0


@dataclass(frozen=True, slots=True)
class ItemEvent:
    """One entry of the append-only history of an item."""

    item_id: UUID
    seq: int
    kind: EventKind
    at: datetime
    actor_id: UUID | None = None
    data: dict[str, Any] = field(default_factory=dict)
