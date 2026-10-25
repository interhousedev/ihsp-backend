"""In-memory FilesApi for LMS tests (only `get` and `get_many` are used)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.contracts.files import (
    FilePurpose,
    FileRef,
    FileScope,
    TextPage,
)
from app.shared.ids import new_id


class FakeFilesApi:
    """Files kept in a dict; `add_file` registers an existing file."""

    def __init__(self) -> None:
        """Start with no files."""
        self.files: dict[UUID, FileRef] = {}

    def add_file(self, *, status: str = "ready") -> FileRef:
        """Register a file and return its reference."""
        ref = FileRef(
            id=new_id(),
            owner_id=new_id(),
            scope=FileScope.COURSE,
            purpose=FilePurpose.LINK,
            name="picture.png",
            content_type="image/png",
            byte_size=10,
            status=status,
            text_bytes=None,
        )
        self.files[ref.id] = ref
        return ref

    async def transfer_ownership(
        self, file_ids: Sequence[UUID], new_owner_id: UUID
    ) -> None:
        """Record the moves (the fake keeps no quota)."""
        self.transferred: list[tuple[UUID, UUID]] = [
            *getattr(self, "transferred", []),
            *((file_id, new_owner_id) for file_id in file_ids),
        ]

    async def get(self, file_id: UUID) -> FileRef | None:
        """Return the file or None."""
        return self.files.get(file_id)

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Return the existing files among the ids."""
        return {fid: self.files[fid] for fid in file_ids if fid in self.files}

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Return a fake URL."""
        return f"https://files.test/{file_id}"

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return empty content."""
        return b""

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Return an empty page."""
        return TextPage(file_id=file_id, page=page, pages=1, text="")

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Nothing matches."""
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
        """Register a new file."""
        return self.add_file()

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Everyone may read."""
        return file_id in self.files
