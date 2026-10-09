"""Hosted books: the form data, building the item from it, status changes (doc § 3.4).

Pure rules. The use cases check that referenced subjects, topics and files exist and
that the caller is a librarian; here are the shape of a book and its life cycle.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from app.modules.library.domain.entities import (
    BookDetails,
    Item,
    SubjectLink,
    TopicLink,
)
from app.modules.library.domain.enums import (
    ItemKind,
    ItemLanguage,
    ItemStatus,
    ItemType,
    Rights,
    StatusReasonCode,
    Visibility,
)
from app.modules.library.domain.errors import NotEditableError
from app.modules.library.domain.rights import check_visibility
from app.modules.library.domain.search_query import build_search_text
from app.modules.library.domain.slugs import make_slug

from pydantic import BaseModel, ConfigDict, Field

AUTHOR_LABEL_MAX = 255

PUBLISHABLE_FROM = frozenset({ItemStatus.DRAFT, ItemStatus.UNPUBLISHED})
UNPUBLISHABLE_FROM = frozenset({ItemStatus.PUBLISHED, ItemStatus.HELD})
TAKEDOWN_FROM = frozenset({ItemStatus.PUBLISHED, ItemStatus.HELD})


class BookData(BaseModel):
    """`BookInput` of the web contract in domain types."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=255)
    subtitle: str | None = Field(default=None, max_length=255)
    authors: list[str] = Field(default_factory=list, max_length=20)
    translators: list[str] = Field(default_factory=list, max_length=20)
    language: ItemLanguage
    year_published: int | None = Field(default=None, ge=-3000, le=2200)
    publisher: str | None = Field(default=None, max_length=255)
    isbn: str | None = Field(default=None, max_length=32)
    type: ItemType
    description: str | None = Field(default=None, max_length=2000)
    years_of_study: list[int] = Field(default_factory=list, max_length=4)
    subjects: list[SubjectLink] = Field(default_factory=list, max_length=20)
    topics: list[TopicLink] = Field(default_factory=list, max_length=100)
    rights: Rights
    licence: str | None = Field(default=None, max_length=40)
    rights_basis: dict[str, object] = Field(default_factory=dict)
    rights_proof_file_id: UUID | None = None
    cover_file_id: UUID | None = None
    visibility: Visibility = Visibility.LYCEUM
    download_allowed: bool = False


def clean_basis(basis: Mapping[str, object]) -> dict[str, object]:
    """The rights basis without empty values."""
    return {k: v for k, v in basis.items() if v is not None and v != ""}


def author_label(authors: Sequence[str]) -> str:
    """The display string of the authors, cut to the column size."""
    return ", ".join(a.strip() for a in authors if a.strip())[:AUTHOR_LABEL_MAX]


def check_book_data(data: BookData) -> None:
    """Rules that need no lookup: visibility against the rights class."""
    check_visibility(data.rights, data.visibility)


def apply_book_data(item: Item, data: BookData, *, now: datetime) -> None:
    """Write the form data into the item (the slug and the status stay)."""
    item.title = data.title.strip()
    item.subtitle = data.subtitle
    item.authors = [a.strip() for a in data.authors if a.strip()]
    item.author_label = author_label(data.authors)
    item.language = data.language
    item.year_published = data.year_published
    item.publisher = data.publisher
    item.isbn = data.isbn
    item.type = data.type
    item.description = data.description
    item.years_of_study = sorted(set(data.years_of_study))
    item.visibility = data.visibility
    item.download_allowed = data.download_allowed
    item.cover_file_id = data.cover_file_id
    item.search_text = build_search_text(
        language=data.language,
        title=item.title,
        subtitle=data.subtitle,
        authors=item.authors,
        description=data.description,
    )
    item.updated_at = now
    item.book = BookDetails(
        rights=data.rights,
        licence=data.licence,
        rights_basis=clean_basis(data.rights_basis),
        rights_proof_file_id=data.rights_proof_file_id,
        rights_checked_by=item.book.rights_checked_by if item.book else None,
        rights_checked_at=item.book.rights_checked_at if item.book else None,
        translators=[t.strip() for t in data.translators if t.strip()],
    )


def new_book(data: BookData, *, item_id: UUID, owner_id: UUID, now: datetime) -> Item:
    """A draft book created by a librarian."""
    item = Item(
        id=item_id,
        slug=make_slug(data.title, item_id),
        kind=ItemKind.BOOK,
        type=data.type,
        title=data.title,
        language=data.language,
        status=ItemStatus.DRAFT,
        visibility=data.visibility,
        created_at=now,
        updated_at=now,
        owner_id=owner_id,
        created_by=owner_id,
    )
    apply_book_data(item, data, now=now)
    return item


def book_data_from(
    item: Item, subjects: Sequence[SubjectLink], topics: Sequence[TopicLink]
) -> BookData:
    """The form data of a stored book (the editor shows it)."""
    details = item.book
    if details is None:
        raise ValueError(f"item {item.id} is not a book")
    return BookData(
        title=item.title,
        subtitle=item.subtitle,
        authors=list(item.authors),
        translators=list(details.translators),
        language=item.language,
        year_published=item.year_published,
        publisher=item.publisher,
        isbn=item.isbn,
        type=item.type,
        description=item.description,
        years_of_study=list(item.years_of_study),
        subjects=list(subjects),
        topics=list(topics),
        rights=details.rights,
        licence=details.licence,
        rights_basis=dict(details.rights_basis),
        rights_proof_file_id=details.rights_proof_file_id,
        cover_file_id=item.cover_file_id,
        visibility=item.visibility,
        download_allowed=item.download_allowed,
    )


# - - - Status changes - - -


def _require(item: Item, allowed: frozenset[ItemStatus], action: str) -> None:
    if item.status not in allowed:
        raise NotEditableError(
            params={"action": action, "status": item.status.value},
            support_details=f"cannot {action} a book that is {item.status.value}",
        )


def publish_book(item: Item, *, actor_id: UUID, now: datetime) -> None:
    """Draft or unpublished book becomes published; the rights check is recorded."""
    _require(item, PUBLISHABLE_FROM, "publish")
    item.status = ItemStatus.PUBLISHED
    item.status_reason = None
    item.status_note = None
    item.published_at = item.published_at or now
    item.reviewed_by = actor_id
    item.reviewed_at = now
    item.updated_at = now
    if item.book is not None:
        item.book.rights_checked_by = actor_id
        item.book.rights_checked_at = now


def unpublish_book(
    item: Item, *, actor_id: UUID, now: datetime, note: str | None
) -> None:
    """A published or held book is withdrawn; the file stays."""
    _require(item, UNPUBLISHABLE_FROM, "unpublish")
    _withdraw(item, StatusReasonCode.UNPUBLISHED, note, actor_id, now)


def take_down_book(item: Item, *, actor_id: UUID, now: datetime, note: str) -> None:
    """A book is removed for a reason (copyright, ...); reason and file are kept."""
    _require(item, TAKEDOWN_FROM, "takedown")
    _withdraw(item, StatusReasonCode.TAKEDOWN, note, actor_id, now)


def _withdraw(
    item: Item,
    reason: StatusReasonCode,
    note: str | None,
    actor_id: UUID,
    now: datetime,
) -> None:
    item.status = ItemStatus.UNPUBLISHED
    item.status_reason = reason.value
    item.status_note = note
    item.reviewed_by = actor_id
    item.reviewed_at = now
    item.updated_at = now
