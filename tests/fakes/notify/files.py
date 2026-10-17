"""A FilesApi that serves prepared files."""

from collections.abc import Sequence
from uuid import UUID

from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.ids import new_id


class FakeFilesApi:
    """Files and their bytes kept in dictionaries."""

    def __init__(self) -> None:
        """Start empty."""
        self.refs: dict[UUID, FileRef] = {}
        self.blobs: dict[UUID, bytes] = {}

    def add(self, name: str, data: bytes) -> FileRef:
        """Store a file and return its reference."""
        ref = FileRef(
            id=new_id(),
            owner_id=new_id(),
            scope=FileScope.SYSTEM,
            purpose=FilePurpose.LINK,
            name=name,
            content_type="application/octet-stream",
            byte_size=len(data),
            status="ready",
            text_bytes=None,
        )
        self.refs[ref.id] = ref
        self.blobs[ref.id] = data
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
        """Return the reference or None."""
        return self.refs.get(file_id)

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the file's bytes."""
        return self.blobs[file_id]
