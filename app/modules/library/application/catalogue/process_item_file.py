"""The scan job `library.process_item_file(item_id, file_id)` (doc §§ 3.5, 8.1).

Extracts the text of a file page by page, indexes it for full-text hits, records the
outline, page count and hashes, and looks for duplicates, personal data and exam-paper
markers. Findings are shown to librarians; no status changes, so a teacher's
published material stays published. A primary file of a book without a cover also
gives it one (PDF first page, EPUB cover image); the user can replace it later.
"""

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.library.application.catalogue.cover_extract import extract_cover
from app.modules.library.domain.catalogue_text import (
    content_hash,
    split_pages,
    text_status_for,
)
from app.modules.library.domain.entities import Item, ItemFile
from app.modules.library.domain.enums import EventKind, ItemKind, TextStatus
from app.modules.library.domain.scan_findings import FindingCode, scan_material_text
from app.modules.library.domain.search_query import (
    build_search_text,
    item_search_language,
)
from app.modules.library.ports.page_repository import IndexedPage
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.contracts.files import (
    FilePurpose,
    FilesApi,
    FileScope,
    OutlineEntry,
)
from app.shared.text import search_normalize

import structlog

log = structlog.get_logger(__name__)

NO_TEXT_CODE = "files/no-text"


@dataclass(slots=True)
class Extracted:
    """What the files module could tell about the file."""

    pages: list[str] = field(default_factory=list)
    failed: bool = False
    outline: list[OutlineEntry] = field(default_factory=list)
    page_count: int | None = None
    sha256: str | None = None

    @property
    def text(self) -> str:
        """All pages joined, for hashing and scanning."""
        return "\n".join(self.pages)


@dataclass(frozen=True, slots=True)
class Findings:
    """The result of the scan, as stored in `material_details.scan`."""

    codes: list[FindingCode]
    duplicate_of: list[UUID]
    at: datetime
    file_id: UUID

    def as_json(self) -> dict[str, object]:
        """The JSON kept with the item (codes only, never the matched text)."""
        return {
            "findings": [code.value for code in self.codes],
            "duplicate_of": [str(item_id) for item_id in self.duplicate_of],
            "file_id": str(self.file_id),
            "scanned_at": self.at.isoformat(),
        }


class ProcessItemFile:
    """Idempotent: running it again replaces the index and the findings."""

    def __init__(
        self, *, uow_factory: UowFactory, files: FilesApi, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files
        self.clock = clock

    async def execute(self, item_id: UUID, file_id: UUID) -> None:
        """Scan one file of one item; a file removed meanwhile is skipped."""
        extracted = await self._extract(file_id)
        async with self.uow_factory() as uow:
            item = await uow.items.get(item_id, lock=True)
            stored = item.file(file_id) if item else None
            if item is None or stored is None or item.kind is ItemKind.EXTERNAL:
                log.info("library_scan_skipped", item_id=str(item_id))
                return
            await self._apply(uow, item, stored, extracted)
            await self._make_cover(item, stored)
            await uow.items.save(item)
            await uow.commit()

    async def _make_cover(self, item: Item, stored: ItemFile) -> None:
        """Give a book without a cover one from its primary file; never fails."""
        if (
            not stored.is_primary
            or item.kind is not ItemKind.BOOK
            or item.cover_file_id
            or item.cover_url
            or item.owner_id is None
        ):
            return
        try:
            data = await self.files.read_bytes(stored.file_id)
            found = await asyncio.to_thread(extract_cover, data, stored.format)
            if found is None:
                return
            image, name = found
            ref = await self.files.store_bytes(
                owner_id=item.owner_id,
                scope=FileScope.LIBRARY,
                purpose=FilePurpose.LIBRARY_COVER,
                name=name,
                data=image,
            )
            item.cover_file_id = ref.id
        except BaseError as error:
            log.warning("library_cover_failed", code=error.code)

    async def _extract(self, file_id: UUID) -> Extracted:
        result = Extracted()
        try:
            full = await self.files.read_text_with_pages(file_id)
            result.pages = split_pages(full.text, full.page_starts)
        except BaseError as error:
            result.failed = error.code != NO_TEXT_CODE
            if result.failed:
                log.warning("library_extraction_failed", code=error.code)
        result.outline = await self._guarded(self.files.read_outline(file_id), [])
        result.page_count = await self._guarded(self.files.page_count(file_id), None)
        result.sha256 = await self._guarded(self.files.sha256(file_id), None)
        return result

    async def _guarded[T](self, call: Awaitable[T], fallback: T) -> T:
        try:
            return await call
        except BaseError:
            return fallback

    async def _apply(
        self,
        uow: LibraryUnitOfWork,
        item: Item,
        stored: ItemFile,
        extracted: Extracted,
    ) -> None:
        language = item_search_language(item.language)
        characters = len(extracted.text.strip())
        pages = extracted.page_count or len(extracted.pages) or 1
        status = _status(extracted, characters, pages)
        stored.pages = pages
        stored.toc = _toc(extracted.outline)
        stored.text_status = status
        stored.sha256 = extracted.sha256 or stored.sha256
        indexed = (
            _index(extracted.pages, language) if status is TextStatus.READY else []
        )
        await uow.pages.replace(item.id, stored.file_id, indexed)
        await uow.items.save_file(stored)
        digest = self._update_item(item, stored, extracted, language, status)
        findings = await self._findings(uow, item, stored, extracted, digest)
        await uow.items.save(item)
        if findings.codes and item.material is None:
            await self._log_book_findings(uow, item, findings)

    def _update_item(
        self,
        item: Item,
        stored: ItemFile,
        extracted: Extracted,
        language: str,
        status: TextStatus,
    ) -> str | None:
        item.has_text = any(f.text_status is TextStatus.READY for f in item.files)
        if stored.is_primary:
            item.page_count = stored.pages
        digest = None
        if status is TextStatus.READY and stored.is_primary:
            digest = content_hash(extracted.text, language)
            item.content_hash = digest
        item.search_text = build_search_text(
            language=item.language,
            title=item.title,
            subtitle=item.subtitle,
            authors=item.authors,
            description=item.description,
        )
        item.updated_at = self.clock.now()
        return digest

    async def _findings(
        self,
        uow: LibraryUnitOfWork,
        item: Item,
        stored: ItemFile,
        extracted: Extracted,
        digest: str | None,
    ) -> Findings:
        duplicates = await _duplicates(uow, item, stored, digest)
        codes: list[FindingCode] = []
        if item.material is not None:
            codes.extend(scan_material_text(extracted.text))
        if duplicates:
            codes.append(FindingCode.DUPLICATE)
        found = Findings(codes, duplicates, self.clock.now(), stored.file_id)
        if item.material is not None:
            item.material.scan = found.as_json()
        return found

    async def _log_book_findings(
        self, uow: LibraryUnitOfWork, item: Item, found: Findings
    ) -> None:
        await uow.events.append(
            item.id,
            EventKind.EDITED,
            at=found.at,
            data={"scan": found.as_json()},
        )


def _status(extracted: Extracted, characters: int, pages: int) -> TextStatus:
    if extracted.failed:
        return TextStatus.FAILED
    return text_status_for(characters, pages)


def _index(pages: Sequence[str], language: str) -> list[IndexedPage]:
    return [
        IndexedPage(number, text, search_normalize(text, language))
        for number, text in enumerate(pages, start=1)
        if text.strip()
    ]


def _toc(outline: Sequence[OutlineEntry]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for entry in outline:
        row: dict[str, object] = {"title": entry.title, "level": entry.level + 1}
        if entry.page is not None:
            row["page"] = entry.page
        if entry.href:
            row["href"] = entry.href
        entries.append(row)
    return entries


async def _duplicates(
    uow: LibraryUnitOfWork, item: Item, stored: ItemFile, digest: str | None
) -> list[UUID]:
    found: dict[UUID, None] = {}
    if stored.sha256:
        for other in await uow.items.find_by_file_hash(stored.sha256, exclude=item.id):
            found[other] = None
    if digest:
        for other in await uow.items.find_by_content_hash(digest, exclude=item.id):
            found[other] = None
    if item.supersedes_id is not None:
        found.pop(item.supersedes_id, None)
    return list(found)
