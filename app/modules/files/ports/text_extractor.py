"""Text extraction from stored files."""

from dataclasses import dataclass
from typing import Protocol

from app.shared.contracts.files import OutlineEntry


@dataclass(frozen=True, slots=True)
class ExtractedText:
    """Text of a file; ``pages``, ``page_starts`` and ``outline`` are set for books.

    ``pages`` counts PDF pages or EPUB chapters. ``page_starts`` holds the character
    offset in ``text`` where each page begins (``text`` joins the page texts with one
    newline). ``outline`` is the table of contents, when the file has one.
    """

    text: str
    pages: int | None = None
    page_starts: tuple[int, ...] = ()
    outline: tuple[OutlineEntry, ...] = ()


class TextExtractor(Protocol):
    """Extracts text from PDF, EPUB, DOCX, TXT and MD."""

    def supports(self, content_type: str) -> bool:
        """Return True for types this extractor can read."""
        ...

    async def extract(self, content_type: str, data: bytes) -> ExtractedText:
        """Return the text; raise TextExtractionError when the file is unreadable."""
        ...
