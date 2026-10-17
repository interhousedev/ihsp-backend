"""Files contracts (provider: files module)."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class FileScope(StrEnum):
    """Whose quota a file counts against."""

    STUDENT = "student"
    STAFF = "staff"
    COURSE = "course"
    MAIL = "mail"
    SYSTEM = "system"
    LIBRARY = "library"


class FilePurpose(StrEnum):
    """Why a file was uploaded."""

    AI_UPLOAD = "ai_upload"
    LINK = "link"
    MAIL = "mail"
    LIBRARY_BOOK = "library_book"
    LIBRARY_COVER = "library_cover"
    LIBRARY_MATERIAL = "library_material"
    LMS_VIDEO = "lms_video"
    USER_PHOTO = "user_photo"


@dataclass(frozen=True, slots=True)
class FileRef:
    """Metadata of a stored file."""

    id: UUID
    owner_id: UUID
    scope: FileScope
    purpose: FilePurpose
    name: str
    content_type: str
    byte_size: int
    status: str
    text_bytes: int | None


@dataclass(frozen=True, slots=True)
class TextPage:
    """One page of a file's extracted text."""

    file_id: UUID
    page: int
    pages: int
    text: str


@dataclass(frozen=True, slots=True)
class FullText:
    """The whole extracted text of a file and where each PDF page starts."""

    file_id: UUID
    text: str
    page_starts: tuple[int, ...]  # character offset of every page in ``text``


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    """One entry of a file's table of contents (PDF outline or EPUB navigation).

    ``level`` starts at 0 for top-level entries. ``page`` is the 1-based PDF page, or
    the 1-based chapter (spine position) of an EPUB; it is None when the target is
    unknown. ``href`` is set for EPUB entries: the path inside the book, relative to
    its package (OPF) folder, with the ``#fragment`` when there is one.
    """

    title: str
    page: int | None
    href: str | None
    level: int


class FilesApi(Protocol):
    """File operations for other modules."""

    async def get(self, file_id: UUID) -> FileRef | None:
        """Return file metadata or None."""
        ...

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Return metadata of the existing files."""
        ...

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Return a presigned download URL, valid 60 s unless ``ttl_seconds`` is set."""
        ...

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the file content."""
        ...

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Return one page of the extracted text."""
        ...

    async def read_text_with_pages(self, file_id: UUID) -> FullText:
        """Return the whole text sidecar with the offset where each page starts.

        ``page_starts`` is empty for files without pages (or processed before page
        offsets were stored). Raises when the file has no text or is deleted.
        """
        ...

    async def read_outline(self, file_id: UUID) -> list[OutlineEntry]:
        """Return the table of contents found while processing (empty if none).

        Files processed before outlines were stored, and types without one, give [].
        """
        ...

    async def page_count(self, file_id: UUID) -> int | None:
        """Return the PDF page count or EPUB chapter count, or None if unknown."""
        ...

    async def sha256(self, file_id: UUID) -> str | None:
        """Return the lower-case hex SHA-256 of the content, or None if unknown."""
        ...

    async def find_by_content(
        self, *, owner_id: UUID, scope: FileScope, sha256: str, byte_size: int
    ) -> FileRef | None:
        """Return a live file of the owner and scope with this content, or None.

        ``sha256`` is the lower-case hex digest; deleted and rejected files are
        never returned.
        """
        ...

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search the owner's files by extracted text."""
        ...

    async def store_bytes(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        data: bytes,
        expires_days: int | None = None,
    ) -> FileRef:
        """Store bytes as a new file."""
        ...

    async def combine_images_to_pdf(
        self,
        file_ids: Sequence[UUID],
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
    ) -> FileRef:
        """Write the owner's uploaded JPEG/PNG files (1 to 20) as one PDF, a page each.

        Raises ``ImageNotSupportedError`` for anything but plain JPEG and PNG.
        """
        ...

    async def delete_file(self, file_id: UUID) -> None:
        """Delete the content, the extracted text and the row for good.

        There is no access check (the caller already decided); unknown ids and files
        that are already gone are fine, so the call can be repeated.
        """
        ...

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """Return the owner's ready, non-deleted files, newest first."""
        ...

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Return True if the actor may read the file.

        The owner and administrators may; files of scope ``library`` are also open to
        librarians. Everyone else reads library files through the library's endpoints.
        """
        ...
