"""Port: who a file is shared with and its link."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.files.domain.sharing import FileShare, FileShareVia


class FileShareRepository(Protocol):
    """Sharing rows of the open transaction."""

    async def find(self, file_id: UUID, user_id: UUID) -> FileShare | None:
        """The person's row, revoked or not."""
        ...

    async def put(self, share: FileShare) -> None:
        """Insert the grant or replace the person's row."""
        ...

    async def delete(self, file_id: UUID, user_id: UUID) -> None:
        """Forget the person's row."""
        ...

    async def delete_via(self, file_id: UUID, via: FileShareVia) -> None:
        """Forget the live grants of one kind."""
        ...

    async def list_active(self, file_id: UUID) -> list[FileShare]:
        """The live grants of a file, oldest first."""
        ...

    async def files_of(self, user_id: UUID) -> list[UUID]:
        """Files shared with the person, newest grant first."""
        ...

    async def delete_for_user(self, user_id: UUID) -> None:
        """Forget every row of a removed account."""
        ...

    async def link_exists(self, file_id: UUID) -> bool:
        """True when the file has an active link."""
        ...

    async def set_link(self, file_id: UUID, token_hash: str, now: datetime) -> None:
        """Create the link or replace its token."""
        ...

    async def delete_link(self, file_id: UUID) -> None:
        """Turn the link off."""
        ...

    async def file_of_token(self, token_hash: str) -> UUID | None:
        """The file of an active link."""
        ...
