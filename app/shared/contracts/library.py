"""Library contracts (provider: the library module).

Consumers: notebooks (`LibrarySourceReader`: books and materials become sources),
academic and subject hubs (`LibraryQueries`: lesson book links, reading lists).
UniLibrary records are never readable through these contracts.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor

UnavailableReason = Literal["not_found", "unavailable", "not_supported", "no_text"]


class LibrarySourceUnavailableError(Exception):
    """The item cannot be used as a source (any more).

    `reason`: `not_found` (missing or not visible to the user), `unavailable`
    (held, taken down, unpublished or rights no longer allow it), `not_supported`
    (a UniLibrary record), `no_text` (scan without extracted text).
    """

    def __init__(self, reason: UnavailableReason, *, item_id: UUID) -> None:
        """Remember the reason and the item."""
        super().__init__(f"{reason}: {item_id}")
        self.reason: UnavailableReason = reason
        self.item_id = item_id


@dataclass(frozen=True, slots=True)
class LibraryFileRef:
    """A file of a library item as a notebook source sees it."""

    file_id: UUID
    format: str  # pdf, epub, md, txt, docx, pptx
    pages: int | None
    text_status: str  # none, pending, ready, no_text, failed
    is_primary: bool


@dataclass(frozen=True, slots=True)
class LibraryItemRef:
    """What a notebook needs to know about a book or a material."""

    id: UUID
    kind: Literal["book", "material"]
    title: str
    author_label: str
    page_count: int | None
    files: tuple[LibraryFileRef, ...]


@dataclass(frozen=True, slots=True)
class LibraryText:
    """The text of a page range of one file; `page_starts` are offsets in `text`."""

    item_id: UUID
    file_id: UUID
    title: str
    page_from: int
    page_to: int
    text: str
    page_starts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LibraryAnnotationRef:
    """One of the student's own annotations on an item."""

    kind: Literal["highlight", "note", "bookmark"]
    quote: str | None
    note: str | None
    page: int | None
    color: str
    updated_at: dt.datetime


class LibrarySourceReader(Protocol):
    """Read access for notebooks; access is re-checked on every call."""

    async def describe(self, item_id: UUID, actor: Actor) -> LibraryItemRef:
        """The item and its files; raises `LibrarySourceUnavailableError`."""
        ...

    async def read_text(
        self,
        item_id: UUID,
        file_id: UUID,
        *,
        actor: Actor,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> LibraryText:
        """The text of a page range (the whole file by default)."""
        ...

    async def read_annotations(
        self, item_id: UUID, *, actor: Actor
    ) -> list[LibraryAnnotationRef]:
        """The actor's own annotations on the item, oldest first."""
        ...


@dataclass(frozen=True, slots=True)
class LessonItemRefView:
    """A lesson follows a section of a book (never overwrites the lesson topic)."""

    item_id: UUID
    title: str
    section_label: str
    page_from: int | None
    page_to: int | None


@dataclass(frozen=True, slots=True)
class ReadingListSummary:
    """A published reading list for a subject, as the subject hub lists it."""

    id: UUID
    title: str
    entries: int
    essential_entries: int


class LibraryQueries(Protocol):
    """Read access for the lesson pages and the subject hub."""

    async def lesson_item_refs(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[LessonItemRefView]]:
        """Book links of the lessons (lessons without a link are absent)."""
        ...

    async def reading_lists_for_subject(
        self, subject_id: UUID, actor: Actor
    ) -> list[ReadingListSummary]:
        """Published lists of the subject that the actor's groups can see."""
        ...
