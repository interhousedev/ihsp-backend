"""FilesApi: what other modules may do with files (contract in shared/contracts)."""

import asyncio
import base64
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.files.application.combine_images_to_pdf import CombineImagesToPdf
from app.modules.files.application.complete_upload import CompleteUpload
from app.modules.files.application.download_links import DownloadLinks
from app.modules.files.application.list_owned_files import ListOwnedFiles
from app.modules.files.application.read_file_bytes import ReadFileBytes
from app.modules.files.application.read_full_text import ReadFullText
from app.modules.files.application.read_outline import ReadOutline
from app.modules.files.application.read_text_page import ReadTextPage
from app.modules.files.application.remove_file import RemoveFile
from app.modules.files.application.request_upload import RequestUpload
from app.modules.files.application.search_text import SearchText
from app.modules.files.application.store_bytes import StoreBytes
from app.modules.files.application.transfer_ownership import TransferOwnership
from app.modules.files.domain.errors import (
    ConfidentialFileError,
    StoredFileNotFoundError,
)
from app.modules.files.domain.outline import pages_from_metadata
from app.modules.files.domain.page_layouts import (
    BOXES_KEY,
    is_ocr,
    layouts_from_metadata,
)
from app.modules.files.domain.policy import checksum_hex, may_read
from app.modules.files.domain.status import FileStatus, ScanStatus
from app.modules.files.infrastructure.extraction.pdf_layout import extract_pdf_layouts
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import (
    FilePurpose,
    FileRef,
    FileScope,
    FullText,
    OutlineEntry,
    PageLayout,
    PresignedPut,
    SignedDownload,
    TextPage,
)

SIGNED_DOWNLOAD_SECONDS = 300


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
        request_upload_uc: RequestUpload,
        complete_upload_uc: CompleteUpload,
        combine_images_uc: CombineImagesToPdf,
        remove_file_uc: RemoveFile,
        list_owned_uc: ListOwnedFiles,
        transfer_uc: TransferOwnership,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._links = links
        self._read_bytes = read_bytes_uc
        self._read_text_page = read_text_page_uc
        self._read_full_text = read_full_text_uc
        self._read_outline = read_outline_uc
        self._search_text = search_text_uc
        self._store_bytes = store_bytes_uc
        self._request_upload = request_upload_uc
        self._complete_upload = complete_upload_uc
        self._combine_images = combine_images_uc
        self._remove_file = remove_file_uc
        self._list_owned = list_owned_uc
        self._transfer = transfer_uc

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

    async def issue_signed_download(
        self, file_id: UUID, *, ttl_seconds: int = SIGNED_DOWNLOAD_SECONDS
    ) -> SignedDownload:
        """Sign a link of a confidential file, valid at most 5 minutes."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None:
            raise StoredFileNotFoundError()
        ttl = max(1, min(ttl_seconds, SIGNED_DOWNLOAD_SECONDS))
        link = await self._links.url_for(
            file, inline=False, ttl_seconds=ttl, allow_confidential=True
        )
        return SignedDownload(url=link.url, expires_at=link.expires_at)

    async def set_scan_status(self, file_id: UUID, scan_status: str) -> None:
        """Record the antivirus result of a file."""
        status = ScanStatus(scan_status)
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
            if file is None:
                raise StoredFileNotFoundError()
            file.set_scan_status(status, self._clock.now())
            await uow.files.save(file)
            await uow.commit()

    async def _refuse_confidential(self, file_id: UUID) -> None:
        """Keep text, outline and layout of a confidential file off the generic API."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is not None and file.confidential:
            raise ConfidentialFileError()

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the content of a file (confidential files are refused)."""
        return await self._read_bytes.execute(file_id)

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Return one 8 KB page (1-based) of the extracted text."""
        await self._refuse_confidential(file_id)
        return await self._read_text_page.execute(file_id, page)

    async def read_text_with_pages(self, file_id: UUID) -> FullText:
        """Return the whole text sidecar and the offset where each PDF page starts."""
        await self._refuse_confidential(file_id)
        return await self._read_full_text.execute(file_id)

    async def read_page_layouts(self, file_id: UUID) -> dict[int, PageLayout]:
        """Return word boxes per page: the OCR result of the file, else the PDF's."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None:
            raise StoredFileNotFoundError()
        if file.confidential:
            raise ConfidentialFileError()
        if is_ocr(file.metadata):
            return layouts_from_metadata(file.metadata.get(BOXES_KEY))
        if file.content_type != "application/pdf":
            return {}
        full = await self._read_full_text.execute(file_id)
        if not full.page_starts:
            return {}
        pages = _stripped_pages(full.text, full.page_starts)
        data = await self._read_bytes.execute(file_id)
        return await asyncio.to_thread(extract_pdf_layouts, data, pages)

    async def read_outline(self, file_id: UUID) -> list[OutlineEntry]:
        """Return the contents found while processing; [] when there are none."""
        await self._refuse_confidential(file_id)
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

    async def find_by_content(
        self, *, owner_id: UUID, scope: FileScope, sha256: str, byte_size: int
    ) -> FileRef | None:
        """Return a live file of the owner and scope with this content, or None."""
        checksum = base64.b64encode(bytes.fromhex(sha256)).decode()
        async with self._uow_factory() as uow:
            file = await uow.files.find_by_checksum(
                owner_id, scope, checksum, byte_size
            )
        return None if file is None else file.to_ref()

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search the owner's files; returns ``{file_id, name, snippet}`` dicts."""
        return await self._search_text.execute(owner_id, query, limit)

    async def search_text_in(
        self, file_ids: Sequence[UUID], query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search only these files; the caller has already decided they are allowed."""
        if file_ids:
            async with self._uow_factory() as uow:
                files = await uow.files.get_many(file_ids)
            if any(file.confidential for file in files):
                raise ConfidentialFileError()
        return await self._search_text.execute_in(file_ids, query, limit)

    async def store_bytes(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        data: bytes,
        expires_days: int | None = None,
        confidential: bool = False,
    ) -> FileRef:
        """Store server-side bytes as a new file (confidential: institution-owned)."""
        file = await self._store_bytes.execute(
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            data=data,
            expires_days=expires_days,
            confidential=confidential,
        )
        return file.to_ref()

    async def store_path(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        path: str,
        content_type: str,
    ) -> FileRef:
        """Store a club file from disk; the type is sniffed, not taken on trust."""
        file = await self._store_bytes.execute_path(
            owner_id=owner_id, scope=scope, purpose=purpose, name=name, path=path
        )
        return file.to_ref()

    async def request_upload(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        size: int,
        content_type: str,
        sha256_b64: str,
        max_bytes: int,
    ) -> tuple[UUID, PresignedPut]:
        """Reserve a club file and return its id and presigned PUT."""
        ticket = await self._request_upload.execute_for_owner(
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            size=size,
            content_type=content_type,
            sha256_b64=sha256_b64,
            max_bytes=max_bytes,
        )
        put = ticket.upload
        return ticket.view.file.id, PresignedPut(put.url, dict(put.headers), put.method)

    async def complete_upload(self, file_id: UUID) -> FileRef:
        """Verify the uploaded club file (size, checksum, sniffed type)."""
        view = await self._complete_upload.execute_club(file_id)
        return view.file.to_ref()

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

    async def transfer_ownership(
        self, file_ids: Sequence[UUID], new_owner_id: UUID
    ) -> None:
        """Give the files to another owner; the old owner's quota no longer counts."""
        await self._transfer.execute(file_ids, new_owner_id)

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


def _stripped_pages(text: str, starts: Sequence[int]) -> list[str]:
    """The page texts cut at ``starts`` and stripped, as the library splits them."""
    bounds = [*starts, len(text)]
    return [text[bounds[i] : bounds[i + 1]].strip() for i in range(len(starts))]
