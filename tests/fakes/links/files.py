"""In-memory FilesApi."""

import hashlib
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
        self.objects: dict[UUID, bytes] = {}  # what store_bytes wrote ("S3")
        self.deleted: list[UUID] = []
        self.refuse: Exception | None = None  # store_bytes raises it when set

    def add(
        self,
        owner_id: UUID,
        *,
        name: str = "Lecture 5.pdf",
        status: str = "ready",
        purpose: FilePurpose = FilePurpose.LINK,
        scope: FileScope = FileScope.STUDENT,
    ) -> FileRef:
        """Create and store a file."""
        file = FileRef(
            id=new_id(),
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            content_type="application/pdf",
            byte_size=1234,
            status=status,
            text_bytes=None,
        )
        self.files[file.id] = file
        return file

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
        """Return the files that exist."""
        return {i: self.files[i] for i in file_ids if i in self.files}

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
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
        """Store a ready file and keep its bytes."""
        if self.refuse is not None:
            raise self.refuse
        file = self.add(owner_id, name=name, purpose=purpose, scope=scope)
        self.objects[file.id] = data
        return file

    async def find_by_content(
        self, *, owner_id: UUID, scope: FileScope, sha256: str, byte_size: int
    ) -> FileRef | None:
        """Return a stored file of the owner and scope with these bytes."""
        for file_id, data in self.objects.items():
            file = self.files.get(file_id)
            if (
                file is not None
                and (file.owner_id, file.scope) == (owner_id, scope)
                and len(data) == byte_size
                and hashlib.sha256(data).hexdigest() == sha256
            ):
                return file
        return None

    async def delete_file(self, file_id: UUID) -> None:
        """Remove the file and its bytes; unknown ids are fine."""
        self.files.pop(file_id, None)
        self.objects.pop(file_id, None)
        self.deleted.append(file_id)

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Allow owners only."""
        file = self.files.get(file_id)
        return file is not None and file.owner_id == actor.user_id
