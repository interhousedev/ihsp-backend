"""Text extraction from stored files."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExtractedText:
    """Text of a file; ``pages`` is set for PDFs."""

    text: str
    pages: int | None = None


class TextExtractor(Protocol):
    """Extracts text from PDF, DOCX, TXT and MD."""

    def supports(self, content_type: str) -> bool:
        """Return True for types this extractor can read."""
        ...

    async def extract(self, content_type: str, data: bytes) -> ExtractedText:
        """Return the text; raise TextExtractionError when the file is unreadable."""
        ...
