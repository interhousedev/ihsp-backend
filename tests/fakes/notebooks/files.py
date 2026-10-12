"""FilesApi for the notebooks tests: the fake of the assistants plus text sidecars."""

import dataclasses
from collections.abc import Sequence
from uuid import UUID

from app.shared.base_error import GoneError, NotFoundError
from app.shared.contracts.files import FileRef, FullText
from tests.fakes.ai.contracts import FakeFiles


class FileNotFound(NotFoundError):
    """The files module's 404."""

    code = "files/not-found"


class FileDeleted(GoneError):
    """The files module's 410."""

    code = "files/deleted"


class FileHasNoText(NotFoundError):
    """The files module's error for a file without extracted text."""

    code = "files/no-text"


class FakeNotebookFiles(FakeFiles):
    """Files with metadata and a full text; ``deleted`` and ``no_text`` age them."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__()
        self.texts: dict[UUID, FullText] = {}
        self.read_calls: list[UUID] = []

    def add_text(
        self, ref: FileRef, text: str, page_starts: Sequence[int] = ()
    ) -> FileRef:
        """Register a file with its extracted text."""
        self.add(ref)
        self.texts[ref.id] = FullText(ref.id, text, tuple(page_starts))
        return ref

    def delete(self, file_id: UUID) -> None:
        """The owner deleted the file (the row stays, like in the files module)."""
        self.files[file_id] = dataclasses.replace(self.files[file_id], status="deleted")

    def drop_text(self, file_id: UUID) -> None:
        """The text sidecar is gone."""
        self.files[file_id] = dataclasses.replace(self.files[file_id], text_bytes=None)

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """A fake presigned URL (the caller has checked the access)."""
        return f"https://files.test/{file_id}"

    async def read_text_with_pages(self, file_id: UUID) -> FullText:
        """Return the text, or fail like the files module does."""
        self.read_calls.append(file_id)
        ref = self.files.get(file_id)
        if ref is None:
            raise FileNotFound()
        if ref.status == "deleted":
            raise FileDeleted()
        if ref.text_bytes is None or file_id not in self.texts:
            raise FileHasNoText()
        return self.texts[file_id]
