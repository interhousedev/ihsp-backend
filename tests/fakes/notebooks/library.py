"""LibrarySourceReader for the notebooks tests: books with pages, access and notes."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.shared.actor import Actor
from app.shared.contracts.library import (
    LibraryAnnotationRef,
    LibraryFileRef,
    LibraryItemRef,
    LibrarySourceUnavailableError,
    LibraryText,
    UnavailableReason,
)
from app.shared.ids import new_id

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


@dataclass(slots=True)
class FakeBook:
    """A book or material: one file, one text per page.

    `denied` is the reason every call fails with (a hold, a takedown, a UniLibrary
    record); `readers` limits who may read it (None: every signed-in user).
    """

    id: UUID
    title: str
    pages: list[str]
    file_id: UUID = field(default_factory=new_id)
    kind: Literal["book", "material"] = "book"
    author_label: str = "A. Author"
    text_status: str = "ready"
    denied: UnavailableReason | None = None
    readers: set[UUID] | None = None


class FakeLibrarySourceReader:
    """`describe`, `read_text` and `read_annotations` with the library's reasons.

    `calls` lists the methods the code under test used, so a test can prove that a
    shared chapter was read once.
    """

    def __init__(self) -> None:
        """Start with an empty library."""
        self.books: dict[UUID, FakeBook] = {}
        self.notes: dict[tuple[UUID, UUID], list[LibraryAnnotationRef]] = {}
        self.calls: list[str] = []

    # - - - Test helpers - - -

    def add_book(
        self,
        title: str = "Physics 10",
        pages: tuple[str, ...] = (
            "Forces change motion.",
            "Newton's first law: a body keeps its state of motion.",
            "Newton's second law: force equals mass times acceleration.",
            "Energy is conserved.",
        ),
        *,
        readers: tuple[UUID, ...] | None = None,
        text_status: str = "ready",
        kind: Literal["book", "material"] = "book",
    ) -> FakeBook:
        """A published book (one page per string)."""
        book = FakeBook(
            id=new_id(),
            title=title,
            pages=list(pages),
            kind=kind,
            text_status=text_status,
            readers=None if readers is None else set(readers),
        )
        self.books[book.id] = book
        return book

    def add_external(self, title: str = "Elektronika") -> FakeBook:
        """A UniLibrary record: it can never be a source."""
        book = self.add_book(title, ())
        book.denied = "not_supported"
        return book

    def hold(self, book: FakeBook) -> None:
        """The item is held or taken down: nobody can use it."""
        book.denied = "unavailable"

    def restore(self, book: FakeBook) -> None:
        """The item is published again."""
        book.denied = None

    def add_note(
        self,
        user_id: UUID,
        book: FakeBook,
        *,
        quote: str | None = "Newton's first law",
        note: str | None = None,
        page: int | None = 2,
        minutes: int = 0,
    ) -> None:
        """A highlight (or note) of the user in the book."""
        kind: Literal["highlight", "note"] = "note" if note else "highlight"
        self.notes.setdefault((user_id, book.id), []).append(
            LibraryAnnotationRef(
                kind=kind,
                quote=quote,
                note=note,
                page=page,
                color="yellow",
                updated_at=NOW + dt.timedelta(minutes=minutes),
            )
        )

    @property
    def text_reads(self) -> int:
        """How many times a text was really read."""
        return self.calls.count("read_text")

    # - - - The contract - - -

    def _open(self, item_id: UUID, actor: Actor) -> FakeBook:
        book = self.books.get(item_id)
        if book is None or (
            book.readers is not None and actor.user_id not in book.readers
        ):
            raise LibrarySourceUnavailableError("not_found", item_id=item_id)
        if book.denied is not None:
            raise LibrarySourceUnavailableError(book.denied, item_id=item_id)
        return book

    async def describe(self, item_id: UUID, actor: Actor) -> LibraryItemRef:
        """The item and its one file."""
        self.calls.append("describe")
        book = self._open(item_id, actor)
        return LibraryItemRef(
            id=book.id,
            kind=book.kind,
            title=book.title,
            author_label=book.author_label,
            page_count=len(book.pages),
            files=(
                LibraryFileRef(
                    file_id=book.file_id,
                    format="pdf",
                    pages=len(book.pages),
                    text_status=book.text_status,
                    is_primary=True,
                ),
            ),
        )

    async def read_text(
        self,
        item_id: UUID,
        file_id: UUID,
        *,
        actor: Actor,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> LibraryText:
        """The pages of the range joined with a newline after each page."""
        self.calls.append("read_text")
        book = self._open(item_id, actor)
        if file_id != book.file_id:
            raise LibrarySourceUnavailableError("not_found", item_id=item_id)
        if book.text_status != "ready":
            raise LibrarySourceUnavailableError("no_text", item_id=item_id)
        first = max(page_from or 1, 1)
        last = min(page_to or len(book.pages), len(book.pages))
        if first > last:
            raise LibrarySourceUnavailableError("no_text", item_id=item_id)
        starts: list[int] = []
        text = ""
        for page in book.pages[first - 1 : last]:
            starts.append(len(text))
            text += page + "\n"
        return LibraryText(
            item_id=book.id,
            file_id=book.file_id,
            title=book.title,
            page_from=first,
            page_to=last,
            text=text,
            page_starts=tuple(starts),
        )

    async def read_annotations(
        self, item_id: UUID, *, actor: Actor
    ) -> list[LibraryAnnotationRef]:
        """The user's own annotations, oldest first."""
        self.calls.append("read_annotations")
        self._open(item_id, actor)
        own = self.notes.get((actor.user_id, item_id), [])
        return sorted(own, key=lambda note: note.updated_at)
