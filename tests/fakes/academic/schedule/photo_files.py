"""In-memory stand-in for the parts of FilesApi the group photo export reads."""

from uuid import UUID

from app.shared.base_error import NotFoundError
from app.shared.ids import new_id


class FakePhotoFiles:
    """Stores file bytes by id; a missing id raises the way the files module does."""

    def __init__(self) -> None:
        """Start without files."""
        self.objects: dict[UUID, bytes] = {}
        self.reads: list[UUID] = []

    def add(self, data: bytes) -> UUID:
        """Store the bytes and return the new file id."""
        file_id = new_id()
        self.objects[file_id] = data
        return file_id

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the content or raise NotFoundError."""
        self.reads.append(file_id)
        if file_id not in self.objects:
            raise NotFoundError(params={"file_id": str(file_id)})
        return self.objects[file_id]
