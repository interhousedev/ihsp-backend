"""FilesApi: what other modules may do with files (contract in shared/contracts)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.files.application.combine_images_to_pdf import CombineImagesToPdf
from app.modules.files.application.download_links import DownloadLinks
from app.modules.files.application.list_owned_files import ListOwnedFiles
from app.modules.files.application.read_file_bytes import ReadFileBytes
from app.modules.files.application.read_full_text import ReadFullText
from app.modules.files.application.read_outline import ReadOutline
from app.modules.files.application.read_text_page import ReadTextPage
from app.modules.files.application.remove_file import RemoveFile
from app.modules.files.application.search_text import SearchText
from app.modules.files.application.store_bytes import StoreBytes
from app.modules.files.domain.errors import StoredFileNotFoundError
from app.modules.files.domain.outline import pages_from_metadata
from app.modules.files.domain.policy import checksum_hex, may_read
from app.modules.files.domain.status import FileStatus
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.files import (
    FilePurpose,
    FileRef,
    FileScope,
    FullText,
    OutlineEntry,
    TextPage,
)


class FilesApiImpl:
    """Implements ``FilesApi`` over the module's use cases."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        links: DownloadLinks,
        read_bytes_uc: ReadFileBytes,
        read_text_page_uc: ReadTextPage,
        read_full_text_uc: ReadFullText,
        read_outline_uc: ReadOutline,
        search_text_uc: SearchText,
        store_bytes_uc: StoreBytes,
        combine_images_uc: CombineImagesToPdf,
        remove_file_uc: RemoveFile,
        list_owned_uc: ListOwnedFiles,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._links = links
        self._read_bytes = read_bytes_uc
        self._read_text_page = read_text_page_uc
        self._read_full_text = read_full_text_uc
        self._read_outline = read_outline_uc
        self._search_text = search_text_uc
        self._store_bytes = store_bytes_uc
        self._combine_images = combine_images_uc
        self._remove_file = remove_file_uc
        self._list_owned = list_owned_uc

    async def get(self, file_id: UUID) -> FileRef | None:
        """Return the file's metadata (also when deleted) or None if unknown."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        return None if file is None else file.to_ref()

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Return the metadata of the files that exist."""
        async with self._uow_factory() as uow:
            files = await uow.files.get_many(list(file_ids))
        return {file.id: file.to_ref() for file in files}

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Return a presigned URL; the caller has already checked access."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None:
            raise StoredFileNotFoundError()
        links = await self._links.url_for(file, inline=inline, ttl_seconds=ttl_seconds)
        return links.url

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the content of a file."""
        return await self._read_bytes.execute(file_id)

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Return one 8 KB page (1-based) of the extracted text."""
        return await self._read_text_page.execute(file_id, page)

    async def read_text_with_pages(self, file_id: UUID) -> FullText:
        """Return the whole text sidecar and the offset where each PDF page starts."""
        return await self._read_full_text.execute(file_id)

    async def read_outline(self, file_id: UUID) -> list[OutlineEntry]:
        """Return the contents found while processing; [] when there are none."""
        return await self._read_outline.execute(file_id)

    async def page_count(self, file_id: UUID) -> int | None:
        """Return the PDF page count or EPUB chapter count; None if not known."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        return None if file is None else pages_from_metadata(file.metadata)

    async def sha256(self, file_id: UUID) -> str | None:
        """Return the content's SHA-256 (lower-case hex) kept at upload, or None."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        return None if file is None else checksum_hex(file.checksum)

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search the owner's files; returns ``{file_id, name, snippet}`` dicts."""
        return await self._search_text.execute(owner_id, query, limit)

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
        """Store server-side bytes as a new file."""
        file = await self._store_bytes.execute(
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            data=data,
            expires_days=expires_days,
        )
        return file.to_ref()

    async def combine_images_to_pdf(
        self,
        file_ids: Sequence[UUID],
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
    ) -> FileRef:
        """Store the owner's JPEG/PNG uploads (1 to 20) as one PDF, a page each."""
        file = await self._combine_images.execute(
            file_ids, owner_id=owner_id, scope=scope, purpose=purpose, name=name
        )
        return file.to_ref()

    async def delete_file(self, file_id: UUID) -> None:
        """Delete the content, the text and the row for good; unknown ids are fine."""
        await self._remove_file.execute(file_id)

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """Return the owner's ready, non-deleted files, newest first."""
        return await self._list_owned.execute(owner_id, limit=limit)

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Owner or administrator (and librarians for library files), not deleted."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None or file.status == FileStatus.DELETED:
            return False
        return may_read(file, actor)
