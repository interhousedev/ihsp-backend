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


class FilePurpose(StrEnum):
    """Why a file was uploaded."""

    AI_UPLOAD = "ai_upload"
    LINK = "link"
    MAIL = "mail"


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


class FilesApi(Protocol):
    """File operations for other modules."""

    async def get(self, file_id: UUID) -> FileRef | None:
        """Return file metadata or None."""
        ...

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Return metadata of the existing files."""
        ...

    async def download_url(self, file_id: UUID, *, inline: bool | None = None) -> str:
        """Return a short-lived presigned download URL."""
        ...

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the file content."""
        ...

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Return one page of the extracted text."""
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

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """Return the owner's ready, non-deleted files, newest first."""
        ...

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Return True if the actor may read the file."""
        ...
