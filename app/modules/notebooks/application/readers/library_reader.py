"""Source kinds `library_item` and `library_notes`: library books as sources (LIB-10).

`library_item` reads a book or a material, whole or a page range (`ref {item_id,
file_id, page_from?, page_to?}`); `library_notes` reads the student's own highlights
and notes in it (`ref {item_id}`). Access is the library's: every call goes through
`LibrarySourceReader`, which re-checks that the item is published and visible to the
owner. When it no longer is, the source becomes `unavailable` instead of `failed`,
and a later sync reads it again.
"""

import asyncio
from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from app.modules.notebooks.application.readers.base import (
    ResolvedSource,
    SourceText,
    clean_title,
    expect_input,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind
from app.modules.notebooks.domain.errors import (
    LibraryNotSupportedError,
    SourceForbiddenError,
    SourceTooLargeError,
    SourceUnavailableError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.library_sources import (
    library_key,
    library_title,
    notes_key,
    notes_version,
    render_notes,
)
from app.modules.notebooks.domain.normalizer import normalize_text
from app.modules.notebooks.domain.source_input import (
    LibraryItemInput,
    LibraryNotesInput,
    SourceInput,
)
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.library import (
    LibraryFileRef,
    LibraryItemRef,
    LibrarySourceReader,
    LibrarySourceUnavailableError,
    LibraryText,
    UnavailableReason,
)

LIBRARY_KINDS: Final = (SourceKind.LIBRARY_ITEM, SourceKind.LIBRARY_NOTES)
READY = "ready"
PENDING = "pending"
# What a source shows for each reason the library gives (the web translates these).
FAILURES: Final[dict[UnavailableReason, SourceFailure]] = {
    "not_found": SourceFailure.DELETED,
    "unavailable": SourceFailure.FORBIDDEN,
    "not_supported": SourceFailure.UNSUPPORTED_TYPE,
    "no_text": SourceFailure.NO_TEXT,
}


def refusal(error: LibrarySourceUnavailableError) -> BaseError:
    """The error of an add request for a reason of the library.

    A missing, hidden or withdrawn item looks the same: the student may not use it.
    """
    details = str(error)
    if error.reason == "not_supported":
        return LibraryNotSupportedError(support_details=details)
    if error.reason == "no_text":
        return SourceUnsupportedError(
            params={"hint": "no_text"}, support_details=details
        )
    return SourceForbiddenError(support_details=details)


def withdrawn(error: LibrarySourceUnavailableError) -> SourceUnavailableError:
    """The error of the pipeline: the source is unavailable, with the shown reason."""
    return SourceUnavailableError(FAILURES[error.reason], support_details=str(error))


def pick_file(ref: LibraryItemRef, file_id: UUID | None) -> LibraryFileRef:
    """The file to read: the one asked for, else the primary one.

    Raises:
        SourceForbiddenError: The file does not belong to the item.
        SourceUnsupportedError: The item has no file.
    """
    if file_id is not None:
        found = next((f for f in ref.files if f.file_id == file_id), None)
        if found is None:
            raise SourceForbiddenError(support_details="file of another item")
        return found
    primary = next((f for f in ref.files if f.is_primary), None)
    chosen = primary or (ref.files[0] if ref.files else None)
    if chosen is None:
        raise SourceUnsupportedError(params={"hint": "no_text"})
    return chosen


def require_ready(item_file: LibraryFileRef) -> None:
    """Raise unless the text of the file is extracted.

    Raises:
        SourceUnsupportedError: A scan without text (`no_text`) or a file whose text
            is still being extracted (`not_ready`).
    """
    if item_file.text_status == READY:
        return
    hint = "not_ready" if item_file.text_status == PENDING else "no_text"
    raise SourceUnsupportedError(params={"hint": hint})


def page_of(ref: dict[str, Any], key: str) -> int | None:
    """A page number stored in a source's `ref`."""
    value = ref.get(key)
    return None if value is None else int(value)


class LibraryReader:
    """Reads library books and the student's notes through the library's contract."""

    def __init__(
        self,
        library: LibrarySourceReader,
        identity: IdentityDirectory,
        *,
        max_chars: int,
    ) -> None:
        """Store the library contract, the user directory and the source size cap."""
        self.library = library
        self.identity = identity
        self.max_chars = max_chars

    # - - - Adding - - -

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """The item must be readable by the student, have text and fit in a source."""
        if isinstance(source_input, LibraryNotesInput):
            return await self._resolve_notes(user_id, source_input)
        return await self._resolve_item(
            user_id, expect_input(source_input, LibraryItemInput)
        )

    async def _resolve_item(
        self, user_id: UUID, item: LibraryItemInput
    ) -> ResolvedSource:
        """A book or a chapter: the real range of pages is stored in the `ref`."""
        actor = await self._actor_or_refuse(user_id)
        ref = await self._described(actor, item.item_id)
        item_file = pick_file(ref, item.file_id)
        require_ready(item_file)
        text = await self._sample(actor, item, item_file)
        ranged = item.page_from is not None or item.page_to is not None
        pages = {"page_from": text.page_from, "page_to": text.page_to} if ranged else {}
        first, last = pages.get("page_from"), pages.get("page_to")
        return ResolvedSource(
            kind=SourceKind.LIBRARY_ITEM,
            title=clean_title(library_title(ref.title, first, last), "Library item"),
            ref={
                "item_id": str(item.item_id),
                "file_id": str(item_file.file_id),
                **pages,
            },
            ref_key=library_key(item_file.file_id, first, last),
            origin={**self._origin(ref), **pages},
        )

    async def _sample(
        self, actor: Actor, item: LibraryItemInput, item_file: LibraryFileRef
    ) -> LibraryText:
        """Read the range once to see that it has text and fits in a source."""
        try:
            text = await self.library.read_text(
                item.item_id,
                item_file.file_id,
                actor=actor,
                page_from=item.page_from,
                page_to=item.page_to,
            )
        except LibrarySourceUnavailableError as exc:
            raise refusal(exc) from exc
        await self._check_size(text.text)
        return text

    async def _resolve_notes(
        self, user_id: UUID, item: LibraryNotesInput
    ) -> ResolvedSource:
        """The student's own highlights and notes; there must be some."""
        actor = await self._actor_or_refuse(user_id)
        ref = await self._described(actor, item.item_id)
        try:
            notes = await self.library.read_annotations(item.item_id, actor=actor)
        except LibrarySourceUnavailableError as exc:
            raise refusal(exc) from exc
        if not render_notes(ref.title, notes):
            raise SourceUnsupportedError(params={"hint": "no_notes"})
        return ResolvedSource(
            kind=SourceKind.LIBRARY_NOTES,
            title=clean_title(f"Notes on {ref.title}", "Library notes"),
            ref={"item_id": str(item.item_id)},
            ref_key=notes_key(item.item_id),
            origin=self._origin(ref),
        )

    @staticmethod
    def _origin(ref: LibraryItemRef) -> dict[str, Any]:
        """What the source list shows about where the text comes from."""
        origin: dict[str, Any] = {
            "item_id": str(ref.id),
            "item_title": ref.title,
            "item_kind": ref.kind,
        }
        if ref.author_label:
            origin["author"] = ref.author_label
        return origin

    async def _described(self, actor: Actor, item_id: UUID) -> LibraryItemRef:
        """The item, or the add error for why the student may not use it."""
        try:
            return await self.library.describe(item_id, actor)
        except LibrarySourceUnavailableError as exc:
            raise refusal(exc) from exc

    async def _check_size(self, text: str) -> None:
        """Refuse a text over the cap and say to pick a chapter instead."""
        size = await asyncio.to_thread(lambda: len(normalize_text(text).text))
        if size > self.max_chars:
            raise SourceTooLargeError(
                params={"hint": "range", "limit": self.max_chars, "chars": size}
            )

    # - - - Reading - - -

    async def read(self, source: Source) -> SourceText:
        """The text of the book or range, or the notes as Markdown.

        Raises:
            SourceUnavailableError: The library no longer lets the owner use it.
            SourceReadError: The notes are empty (`no_text`).
        """
        actor = await self._owner(source)
        item_id = UUID(str(source.ref["item_id"]))
        try:
            if source.kind is SourceKind.LIBRARY_NOTES:
                return await self._read_notes(source, item_id, actor)
            return await self._read_item(source, item_id, actor)
        except LibrarySourceUnavailableError as exc:
            raise withdrawn(exc) from exc

    async def _read_item(
        self, source: Source, item_id: UUID, actor: Actor
    ) -> SourceText:
        """Pages of a file; a chapter's pages are numbered like the book's."""
        text = await self.library.read_text(
            item_id,
            UUID(str(source.ref["file_id"])),
            actor=actor,
            page_from=page_of(source.ref, "page_from"),
            page_to=page_of(source.ref, "page_to"),
        )
        # The chunker numbers pages from the first start, so a chapter starting on
        # page 54 gets 53 empty pages in front of it: its passages say p. 54, p. 55.
        leading = (0,) * (text.page_from - 1)
        return SourceText(text=text.text, page_starts=leading + text.page_starts)

    async def _read_notes(
        self, source: Source, item_id: UUID, actor: Actor
    ) -> SourceText:
        """The student's annotations as Markdown; the fingerprint is the version."""
        notes = await self.library.read_annotations(item_id, actor=actor)
        title = str((source.origin or {}).get("item_title") or source.title)
        return SourceText(
            text=render_notes(title, notes), upstream_version=notes_version(notes)
        )

    async def current_version(self, source: Source) -> str | None:
        """The fingerprint of the notes now; books never change (None)."""
        if source.kind is not SourceKind.LIBRARY_NOTES:
            return None
        actor = await self._actor(source.owner_id)
        if actor is None:
            return None
        try:
            notes = await self.library.read_annotations(
                UUID(str(source.ref["item_id"])), actor=actor
            )
        except LibrarySourceUnavailableError:
            return None
        return notes_version(notes)

    # - - - Checks for the sweep - - -

    async def unavailable(self, sources: Sequence[Source]) -> set[UUID]:
        """Ids of the library sources the owner may not use any more."""
        return (await self._usable(sources))[1]

    async def available(self, sources: Sequence[Source]) -> set[UUID]:
        """Ids of the library sources the owner may use right now."""
        return (await self._usable(sources))[0]

    async def _usable(self, sources: Sequence[Source]) -> tuple[set[UUID], set[UUID]]:
        """Split the sources in (usable, blocked) with one lookup per owner and item."""
        usable: set[UUID] = set()
        blocked: set[UUID] = set()
        actors: dict[UUID, Actor | None] = {}
        refs: dict[tuple[UUID, UUID], LibraryItemRef | None] = {}
        for source in sources:
            if source.kind not in LIBRARY_KINDS:
                continue
            if source.owner_id not in actors:
                actors[source.owner_id] = await self._actor(source.owner_id)
            ref = await self._ref_of(source, actors[source.owner_id], refs)
            (usable if _fits(source, ref) else blocked).add(source.id)
        return usable, blocked

    async def _ref_of(
        self,
        source: Source,
        actor: Actor | None,
        cache: dict[tuple[UUID, UUID], LibraryItemRef | None],
    ) -> LibraryItemRef | None:
        """The item as its owner sees it now; None when the owner cannot use it."""
        if actor is None:
            return None
        item_id = UUID(str(source.ref["item_id"]))
        key = (actor.user_id, item_id)
        if key not in cache:
            try:
                cache[key] = await self.library.describe(item_id, actor)
            except LibrarySourceUnavailableError:
                cache[key] = None
        return cache[key]

    # - - - People - - -

    async def _actor(self, user_id: UUID) -> Actor | None:
        """The user as an actor for the library's checks, None when unknown."""
        user = await self.identity.get_user(user_id)
        return None if user is None else Actor(user_id=user.id, roles=user.roles)

    async def _actor_or_refuse(self, user_id: UUID) -> Actor:
        actor = await self._actor(user_id)
        if actor is None:
            raise SourceForbiddenError(support_details="unknown user")
        return actor

    async def _owner(self, source: Source) -> Actor:
        """The owner of a source as an actor; a missing account ends the source."""
        actor = await self._actor(source.owner_id)
        if actor is None:
            raise SourceUnavailableError(
                SourceFailure.DELETED.value, support_details="unknown owner"
            )
        return actor


def _fits(source: Source, ref: LibraryItemRef | None) -> bool:
    """True when the item is usable and (for a book) the file still has its text."""
    if ref is None:
        return False
    if source.kind is not SourceKind.LIBRARY_ITEM:
        return True
    file_id = UUID(str(source.ref["file_id"]))
    return any(f.file_id == file_id and f.text_status == READY for f in ref.files)
