"""TextExtractor that dispatches by content type and runs parsers off the loop."""

import asyncio
from collections.abc import Callable

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.domain.policy import DOCX, EPUB, PDF
from app.modules.files.infrastructure.extraction.docx_text import extract_docx
from app.modules.files.infrastructure.extraction.epub_text import extract_epub
from app.modules.files.infrastructure.extraction.limits import (
    EXTRACT_TIMEOUT_SECONDS,
)
from app.modules.files.infrastructure.extraction.pdf_text import extract_pdf
from app.modules.files.infrastructure.extraction.plain_text import extract_plain
from app.modules.files.ports.text_extractor import ExtractedText

_PARSERS: dict[str, Callable[[bytes], ExtractedText]] = {
    PDF: extract_pdf,
    EPUB: extract_epub,
    DOCX: extract_docx,
    "text/plain": extract_plain,
    "text/markdown": extract_plain,
}


class FileTextExtractor:
    """Extracts text from PDF, EPUB, DOCX, TXT and MD files."""

    def __init__(self, timeout_seconds: float = EXTRACT_TIMEOUT_SECONDS) -> None:
        """Set how long one file may take."""
        self._timeout = timeout_seconds

    def supports(self, content_type: str) -> bool:
        """Return True for PDF, EPUB, DOCX, plain text and Markdown."""
        return content_type in _PARSERS

    async def extract(self, content_type: str, data: bytes) -> ExtractedText:
        """Parse the file in a worker thread; remove NUL characters (PostgreSQL)."""
        parser = _PARSERS[content_type]
        try:
            async with asyncio.timeout(self._timeout):
                result = await asyncio.to_thread(parser, data)
        except TimeoutError as exc:
            raise TextExtractionError("extraction timed out") from exc
        return ExtractedText(
            text=result.text.replace("\x00", ""),
            pages=result.pages,
            page_starts=result.page_starts,
            outline=result.outline,
        )
