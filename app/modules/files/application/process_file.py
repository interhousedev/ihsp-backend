"""Process an accepted upload: extract text, store the sidecar, index, mark ready."""

from typing import Any
from uuid import UUID

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.domain.outline import OUTLINE_KEY, PAGES_KEY, outline_to_metadata
from app.modules.files.domain.status import FileStatus, RejectReason
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.text_extractor import ExtractedText, TextExtractor
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

import structlog

log = structlog.get_logger(__name__)

TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"


class ProcessFile:
    """Background step of an upload (FILE-7); safe to run twice."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        storage: ObjectStorage,
        extractor: TextExtractor,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._extractor = extractor
        self._clock = clock

    async def execute(self, file_id: UUID) -> None:
        """Extract text when the type supports it; errors leave the file usable."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None or file.status != FileStatus.PROCESSING:
            return
        if await self._storage.head(file.key) is None:
            await self._reject_missing(file_id)
            return
        extracted = await self._extract(file)
        text = extracted.text if extracted else ""
        text_bytes = await self._store_text(file, text)
        await self._finish(file_id, text, text_bytes, extracted)

    async def _extract(self, file: StoredFile) -> ExtractedText | None:
        """Return the file's text, or None when it has none or cannot be read."""
        if not self._extractor.supports(file.content_type):
            return None
        data = await self._storage.get(file.key)
        try:
            return await self._extractor.extract(file.content_type, data)
        except TextExtractionError as exc:
            log.warning("text_extraction_failed", file_id=str(file.id), error=str(exc))
            return None

    async def _store_text(self, file: StoredFile, text: str) -> int | None:
        """Write the text sidecar; return its size in bytes, or None without text."""
        if not text.strip():
            return None
        encoded = text.encode()
        await self._storage.put(file.text_key, encoded, TEXT_CONTENT_TYPE)
        return len(encoded)

    async def _finish(
        self,
        file_id: UUID,
        text: str,
        text_bytes: int | None,
        extracted: ExtractedText | None,
    ) -> None:
        """Index the text and mark the file ready, unless someone else did."""
        metadata = _metadata(extracted, text_bytes)
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
            if file is None or file.status != FileStatus.PROCESSING:
                return
            file.mark_ready(self._clock.now(), text_bytes=text_bytes, metadata=metadata)
            await uow.files.save(file)
            if text_bytes is not None:
                await uow.files.set_text(file_id, text_bytes, text)
            await uow.commit()

    async def _reject_missing(self, file_id: UUID) -> None:
        """The object vanished before processing: reject instead of retrying."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
            if file is None or file.status != FileStatus.PROCESSING:
                return
            file.reject(RejectReason.PROCESSING_FAILED, self._clock.now())
            await uow.files.save(file)
            await uow.commit()


def _metadata(
    extracted: ExtractedText | None, text_bytes: int | None
) -> dict[str, Any]:
    """Return the file metadata: page count and outline, page offsets with text."""
    metadata: dict[str, Any] = {}
    if extracted is None:
        return metadata
    if extracted.pages:
        metadata[PAGES_KEY] = extracted.pages
    if extracted.page_starts and text_bytes is not None:
        metadata["page_starts"] = list(extracted.page_starts)
    if extracted.outline:
        metadata[OUTLINE_KEY] = outline_to_metadata(extracted.outline)
    return metadata
