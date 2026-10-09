"""The readers of all source kinds in one place."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.notebooks.application.readers.base import (
    ResolvedSource,
    SourceReader,
    VersionedReader,
)
from app.modules.notebooks.application.readers.chat_reader import ChatReader
from app.modules.notebooks.application.readers.file_reader import FileReader
from app.modules.notebooks.application.readers.flashcard_reader import (
    FlashcardReader,
)
from app.modules.notebooks.application.readers.lesson_resource_reader import (
    LessonResourceReader,
)
from app.modules.notebooks.application.readers.library_reader import LibraryReader
from app.modules.notebooks.application.readers.lms_reader import LmsReader
from app.modules.notebooks.application.readers.text_reader import TextReader
from app.modules.notebooks.application.readers.url_reader import UrlReader
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.errors import SourceUnsupportedError
from app.modules.notebooks.domain.source_input import SourceInput
from app.modules.notebooks.ports.web_fetcher import WebFetcher
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.library import LibrarySourceReader
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import LmsSourceReader, LmsWorkspace

FILE_BACKED = (SourceKind.FILE, SourceKind.LESSON_RESOURCE)


class SourceReaders:
    """Maps a source kind to its reader; kinds without a reader are unsupported."""

    def __init__(
        self,
        *,
        files: FilesApi,
        ai: AiQueries,
        links: LinksApi,
        schedule: ScheduleQueries,
        flashcards: FlashcardsApi,
        lms: LmsSourceReader | None,
        fetcher: WebFetcher | None,
        blocked_domains: Sequence[str] = (),
        workspace: LmsWorkspace | None = None,
        library: LibrarySourceReader | None = None,
        identity: IdentityDirectory | None = None,
        source_max_chars: int = 600_000,
    ) -> None:
        """Build one reader per kind (`lms`, `fetcher`, `workspace` may be missing).

        URL sources of `blocked_domains` (and their subdomains) are refused. `lms`
        reads live steps for students, `workspace` the draft steps of a course
        workspace. `library` (with `identity`, which gives the owner's roles for the
        library's access checks) reads books and notes; `source_max_chars` is the
        cap a whole book must stay under.
        """
        self.file_reader = FileReader(files)
        url_reader = UrlReader(fetcher, blocked_domains)
        self.lesson_reader = LessonResourceReader(
            links=links,
            schedule=schedule,
            files=files,
            file_reader=self.file_reader,
            url_reader=url_reader,
        )
        text_reader = TextReader()
        chat_reader = ChatReader(ai)
        flashcard_reader = FlashcardReader(flashcards)
        self._readers: dict[SourceKind, SourceReader] = {
            SourceKind.FILE: self.file_reader,
            SourceKind.CHAT: chat_reader,
            SourceKind.LESSON_RESOURCE: self.lesson_reader,
            SourceKind.FLASHCARD_SET: flashcard_reader,
            SourceKind.TEXT: text_reader,
            SourceKind.NOTE: text_reader,
            SourceKind.URL: url_reader,
        }
        self._versioned: dict[SourceKind, VersionedReader] = {
            SourceKind.CHAT: chat_reader,
            SourceKind.FLASHCARD_SET: flashcard_reader,
        }
        if lms is not None or workspace is not None:
            lms_reader = LmsReader(lms, workspace)
            self._readers[SourceKind.LMS_STEP] = lms_reader
            self._versioned[SourceKind.LMS_STEP] = lms_reader
        self.library_reader: LibraryReader | None = None
        if library is not None and identity is not None:
            self.library_reader = LibraryReader(
                library, identity, max_chars=source_max_chars
            )
            self._readers[SourceKind.LIBRARY_ITEM] = self.library_reader
            self._readers[SourceKind.LIBRARY_NOTES] = self.library_reader
            self._versioned[SourceKind.LIBRARY_NOTES] = self.library_reader

    def for_kind(self, kind: SourceKind) -> SourceReader:
        """The reader of a kind.

        Raises:
            SourceUnsupportedError: The kind is not available (`web_result`, or LMS
                steps without an LMS).
        """
        reader = self._readers.get(kind)
        if reader is None:
            raise SourceUnsupportedError(params={"hint": "kind", "kind": kind.value})
        return reader

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """Check an item of an add request with the reader of its kind."""
        reader = self.for_kind(SourceKind(source_input.kind))
        return await reader.resolve(user_id, source_input)

    def is_versioned(self, kind: SourceKind) -> bool:
        """True for kinds whose upstream object can change after the snapshot."""
        return kind in self._versioned

    async def current_version(self, source: Source) -> str | None:
        """The upstream version now; None for other kinds or a missing object."""
        reader = self._versioned.get(source.kind)
        return None if reader is None else await reader.current_version(source)

    def is_file_backed(self, source: Source) -> bool:
        """True for `file` sources and lesson materials that are files."""
        return source.kind in FILE_BACKED and "file_id" in source.ref

    async def unavailable_files(self, sources: Sequence[Source]) -> set[UUID]:
        """Ids of the file-backed sources whose file is deleted or has no text."""
        backed = [s for s in sources if self.is_file_backed(s)]
        return await self.file_reader.unavailable(backed)

    async def unavailable_library(self, sources: Sequence[Source]) -> set[UUID]:
        """Ids of the library sources whose owner may not use the item (any more)."""
        if self.library_reader is None:
            return set()
        return await self.library_reader.unavailable(sources)

    async def available_library(self, sources: Sequence[Source]) -> set[UUID]:
        """Ids of the library sources whose owner may use the item right now."""
        if self.library_reader is None:
            return set()
        return await self.library_reader.available(sources)
