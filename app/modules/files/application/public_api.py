"""FilesApi: what other modules may do with files (contract in shared/contracts)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.files.application.download_links import DownloadLinks
from app.modules.files.application.list_owned_files import ListOwnedFiles
from app.modules.files.application.read_file_bytes import ReadFileBytes
from app.modules.files.application.read_text_page import ReadTextPage
from app.modules.files.application.search_text import SearchText
from app.modules.files.application.store_bytes import StoreBytes
from app.modules.files.domain.errors import StoredFileNotFoundError
from app.modules.files.domain.status import FileStatus
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.files import (
    FilePurpose,
    FileRef,
    FileScope,
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
        search_text_uc: SearchText,
        store_bytes_uc: StoreBytes,
        list_owned_uc: ListOwnedFiles,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._links = links
        self._read_bytes = read_bytes_uc
        self._read_text_page = read_text_page_uc
        self._search_text = search_text_uc
        self._store_bytes = store_bytes_uc
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

    async def download_url(self, file_id: UUID, *, inline: bool | None = None) -> str:
        """Return a presigned URL; the caller has already checked access."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None:
            raise StoredFileNotFoundError()
        return (await self._links.url_for(file, inline=inline)).url

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the content of a file."""
        return await self._read_bytes.execute(file_id)

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Return one 8 KB page (1-based) of the extracted text."""
        return await self._read_text_page.execute(file_id, page)

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

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """Return the owner's ready, non-deleted files, newest first."""
        return await self._list_owned.execute(owner_id, limit=limit)

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Owner or administrator, and the file is not deleted."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None or file.status == FileStatus.DELETED:
            return False
        return file.is_owned_by(actor.user_id) or actor.has(Role.ADMIN)
