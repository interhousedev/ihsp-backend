"""Persistence port of file metadata."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.files.domain.stored_file import StoredFile
from app.shared.contracts.files import FilePurpose, FileScope


class FileRepository(Protocol):
    """Reads and writes file rows; transactions belong to the unit of work."""

    async def lock_owner(self, owner_id: UUID) -> None:
        """Take a transaction-scoped advisory lock for the owner's quota check."""
        ...

    async def used_bytes(
        self, owner_id: UUID, scope: FileScope, term_id: UUID | None
    ) -> int:
        """Sum the bytes of pending, processing and ready files counting to a quota.

        Students: the files of the term. Staff: all their staff files.
        """
        ...

    async def add(self, file: StoredFile) -> None:
        """Insert a new row."""
        ...

    async def save(self, file: StoredFile) -> None:
        """Write the changed fields of an existing row."""
        ...

    async def get(self, file_id: UUID) -> StoredFile | None:
        """Return the file or None."""
        ...

    async def get_many(self, file_ids: Sequence[UUID]) -> list[StoredFile]:
        """Return the existing files (any status)."""
        ...

    async def find_by_checksum(
        self, owner_id: UUID, scope: FileScope, checksum: str, byte_size: int
    ) -> StoredFile | None:
        """Return a live (not deleted or rejected) file with this content."""
        ...

    async def list_for_owner(
        self,
        owner_id: UUID,
        *,
        purpose: FilePurpose | None,
        after: tuple[datetime, UUID] | None,
        limit: int,
        name_query: str | None = None,
        content_types: Sequence[str] | None = None,
        oldest_first: bool = False,
        offset: int = 0,
    ) -> list[StoredFile]:
        """List non-deleted files, newest first, after a (created_at, id) cursor.

        `name_query` matches the name (case-insensitive substring), `content_types`
        keeps only those types, `offset` pages without a cursor.
        """
        ...

    async def list_ready(self, owner_id: UUID, limit: int) -> list[StoredFile]:
        """List the owner's ready files, newest first."""
        ...

    async def list_for_owner_all(self, owner_id: UUID, limit: int) -> list[StoredFile]:
        """List every non-deleted file of the owner (for deleting an account)."""
        ...

    async def set_text(self, file_id: UUID, text_bytes: int, content: str) -> None:
        """Store the text size and build the search vector from the text."""
        ...

    async def headline(self, document: str, query: str) -> str:
        """Return a short fragment of the document around the query words."""
        ...

    async def search(self, owner_id: UUID, query: str, limit: int) -> list[StoredFile]:
        """Return ready files of the owner whose text matches, best first."""
        ...

    async def student_term_ids(self) -> list[UUID]:
        """Return the terms that have student files not yet deleted."""
        ...

    async def list_expired(
        self, *, expired_term_ids: Sequence[UUID], now: datetime, limit: int
    ) -> list[StoredFile]:
        """Return not-deleted files of expired terms or past their expires_at."""
        ...

    async def term_owner_counts(self, term_id: UUID) -> list[tuple[UUID, int]]:
        """Return (owner_id, files_count) for the term's live student files."""
        ...

    async def list_stale_uploads(
        self, older_than: datetime, limit: int
    ) -> list[StoredFile]:
        """Return pending and rejected files created before the moment."""
        ...

    async def list_stale_processing(
        self, older_than: datetime, limit: int
    ) -> list[StoredFile]:
        """Return files stuck in processing since before the moment."""
        ...

    async def mark_deleted(self, file_ids: Sequence[UUID], now: datetime) -> None:
        """Soft-delete rows and clear their search vectors."""
        ...

    async def delete_rows(self, file_ids: Sequence[UUID]) -> None:
        """Remove rows entirely (abandoned uploads)."""
        ...
