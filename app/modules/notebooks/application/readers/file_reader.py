"""Source kind `file`: the extracted text of one of My files (§ 3.2.1)."""

from collections.abc import Sequence
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
    SourceForbiddenError,
    SourceReadError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import FileInput, SourceInput
from app.shared.base_error import GoneError, NotFoundError
from app.shared.contracts.files import FileRef, FilesApi

READY = "ready"
NO_TEXT_CODE = "files/no-text"  # the files module's error for a file without text


def file_id_of(source: Source) -> UUID | None:
    """The file behind a `file` source or a file-based lesson material."""
    raw = source.ref.get("file_id")
    return UUID(str(raw)) if raw else None


def has_text(ref: FileRef | None) -> bool:
    """True when the file exists, is ready and has an extracted text."""
    return ref is not None and ref.status == READY and ref.text_bytes is not None


def require_text(ref: FileRef) -> None:
    """Raise when the file cannot be a source because it has no text.

    Raises:
        SourceUnsupportedError: The file is not ready or has no extracted text.
    """
    if ref.status != READY:
        raise SourceUnsupportedError(params={"hint": "not_ready"})
    if ref.text_bytes is None:
        raise SourceUnsupportedError(params={"hint": "no_text"})


class FileReader:
    """Reads the text sidecar of a file with the offsets of its pages."""

    def __init__(self, files: FilesApi) -> None:
        """Store the files API."""
        self.files = files

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """The file must be the user's own, ready and have text."""
        item = expect_input(source_input, FileInput)
        ref = await self.files.get(item.file_id)
        if ref is None or ref.owner_id != user_id or ref.status == "deleted":
            raise SourceForbiddenError()
        require_text(ref)
        return ResolvedSource(
            kind=SourceKind.FILE,
            title=clean_title(ref.name, "File"),
            ref={"file_id": str(ref.id)},
            ref_key=f"file:{ref.id}",
        )

    async def read(self, source: Source) -> SourceText:
        """Return the whole text and the page starts of the file."""
        file_id = file_id_of(source)
        if file_id is None:
            raise SourceReadError(SourceFailure.DELETED.value)
        return await self.read_file(file_id)

    async def read_file(self, file_id: UUID) -> SourceText:
        """Read a file by id (also used for file-based lesson materials)."""
        try:
            full = await self.files.read_text_with_pages(file_id)
        except GoneError as exc:
            raise SourceReadError(SourceFailure.DELETED.value) from exc
        except NotFoundError as exc:
            failure = (
                SourceFailure.NO_TEXT
                if exc.code == NO_TEXT_CODE
                else SourceFailure.DELETED
            )
            raise SourceReadError(failure.value) from exc
        return SourceText(text=full.text, page_starts=tuple(full.page_starts))

    async def unavailable(self, sources: Sequence[Source]) -> set[UUID]:
        """Ids of the sources whose file was deleted or has no text any more."""
        wanted = {s.id: file_id_of(s) for s in sources}
        file_ids = [f for f in wanted.values() if f is not None]
        if not file_ids:
            return set()
        found = await self.files.get_many(file_ids)
        return {
            source_id
            for source_id, file_id in wanted.items()
            if file_id is not None and not has_text(found.get(file_id))
        }
