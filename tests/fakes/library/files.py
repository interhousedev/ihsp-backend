"""In-memory FilesApi subset for the library tests (bytes, text pages, URLs)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.contracts.files import (
    FilePurpose,
    FileRef,
    FileScope,
    FullText,
    OutlineEntry,
    TextPage,
)
from app.shared.ids import new_id


@dataclass(slots=True)
class StoredFile:
    """One stored file with optional page texts."""

    ref: FileRef
    data: bytes = b""
    pages: list[str] = field(default_factory=list)
    sha256: str | None = None
    outline: list[OutlineEntry] = field(default_factory=list)


class FakeFilesApi:
    """Files by id; `add_file` creates one, `urls` records the TTLs asked for."""

    def __init__(self) -> None:
        """Start empty."""
        self.files: dict[UUID, StoredFile] = {}
        self.urls: list[tuple[UUID, int | None]] = []

    def add_file(
        self,
        *,
        owner_id: UUID,
        name: str = "book.pdf",
        content_type: str = "application/pdf",
        data: bytes = b"%PDF-1.4",
        pages: Sequence[str] = (),
        scope: FileScope = FileScope.SYSTEM,
        purpose: FilePurpose = FilePurpose.LINK,
        sha256: str | None = None,
    ) -> UUID:
        """Create a ready file; `pages` are its extracted page texts."""
        file_id = new_id()
        ref = FileRef(
            id=file_id,
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            content_type=content_type,
            byte_size=len(data),
            status="ready",
            text_bytes=sum(len(p) for p in pages) or None,
        )
        self.files[file_id] = StoredFile(ref, data, list(pages), sha256)
        return file_id

    def _stored(self, file_id: UUID) -> StoredFile:
        stored = self.files.get(file_id)
        if stored is None:
            raise NotFoundError(support_details=f"no file {file_id}")
        return stored

    async def get(self, file_id: UUID) -> FileRef | None:
        """Metadata or None."""
        stored = self.files.get(file_id)
        return stored.ref if stored else None

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Metadata of the existing files."""
        return {fid: self.files[fid].ref for fid in file_ids if fid in self.files}

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """A fake URL that names the file and the TTL."""
        self._stored(file_id)
        self.urls.append((file_id, ttl_seconds))
        return f"https://files.test/{file_id}?ttl={ttl_seconds}&inline={inline}"

    async def read_bytes(self, file_id: UUID) -> bytes:
        """The content."""
        return self._stored(file_id).data

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """One extracted page (1-based)."""
        stored = self._stored(file_id)
        return TextPage(file_id, page, len(stored.pages), stored.pages[page - 1])

    async def read_text_with_pages(self, file_id: UUID) -> FullText:
        """All text with the offset of each page."""
        stored = self._stored(file_id)
        starts: list[int] = []
        text = ""
        for page in stored.pages:
            starts.append(len(text))
            text += page + "\n"
        return FullText(file_id, text, tuple(starts))

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
        file_id = self.add_file(
            owner_id=owner_id, name=name, data=data, scope=scope, purpose=purpose
        )
        return self.files[file_id].ref

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """The owner may read."""
        return self._stored(file_id).ref.owner_id == actor.user_id

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Unused by the library."""
        return []

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """Unused by the library."""
        return []

    async def sha256(self, file_id: UUID) -> str | None:
        """The configured hash."""
        return self._stored(file_id).sha256

    async def page_count(self, file_id: UUID) -> int | None:
        """The number of configured pages, or None."""
        return len(self._stored(file_id).pages) or None

    async def read_outline(self, file_id: UUID) -> list[OutlineEntry]:
        """The configured outline (empty by default)."""
        return list(self._stored(file_id).outline)

    async def combine_images_to_pdf(
        self,
        file_ids: Sequence[UUID],
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
    ) -> FileRef:
        """A new PDF file made of the given images (the content is a stub)."""
        for file_id in file_ids:
            self._stored(file_id)
        new_id_ = self.add_file(
            owner_id=owner_id,
            name=name if name.endswith(".pdf") else f"{name}.pdf",
            scope=scope,
            purpose=purpose,
            pages=[f"page {n + 1}" for n in range(len(file_ids))],
        )
        return self.files[new_id_].ref

    async def delete_file(self, file_id: UUID) -> None:
        """Forget the file (already gone is fine)."""
        self.files.pop(file_id, None)
