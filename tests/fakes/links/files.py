"""In-memory FilesApi."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.contracts.files import (
    FilePurpose,
    FileRef,
    FileScope,
    TextPage,
)
from app.shared.ids import new_id


class FakeFiles:
    """Keeps FileRef objects in a dict; download URLs are fake HTTPS URLs."""

    def __init__(self) -> None:
        """Start with no files."""
        self.files: dict[UUID, FileRef] = {}

    def add(
        self,
        owner_id: UUID,
        *,
        name: str = "Lecture 5.pdf",
        status: str = "ready",
        purpose: FilePurpose = FilePurpose.LINK,
    ) -> FileRef:
        """Create and store a file."""
        file = FileRef(
            id=new_id(),
            owner_id=owner_id,
            scope=FileScope.STUDENT,
            purpose=purpose,
            name=name,
            content_type="application/pdf",
            byte_size=1234,
            status=status,
            text_bytes=None,
        )
        self.files[file.id] = file
        return file

    async def get(self, file_id: UUID) -> FileRef | None:
        """Return the file or None."""
        return self.files.get(file_id)

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Return the files that exist."""
        return {i: self.files[i] for i in file_ids if i in self.files}

    async def download_url(self, file_id: UUID, *, inline: bool | None = None) -> str:
        """Return a presigned-looking URL or raise NotFoundError."""
        file = self.files.get(file_id)
        if file is None or file.status == "deleted":
            raise NotFoundError()
        return f"https://storage.test/{file_id}?sig=abc"

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return empty content."""
        return b""

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Return an empty page."""
        return TextPage(file_id=file_id, page=page, pages=1, text="")

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Find nothing."""
        return []

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
        """Store a ready file."""
        return self.add(owner_id, name=name, purpose=purpose)

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Allow owners only."""
        file = self.files.get(file_id)
        return file is not None and file.owner_id == actor.user_id
