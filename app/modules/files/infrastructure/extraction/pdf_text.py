"""Text of PDF files (pypdf, pure Python; blocking)."""

import io

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction.limits import (
    MAX_PDF_PAGES,
    MAX_TEXT_CHARS,
)
from app.modules.files.ports.text_extractor import ExtractedText

from pypdf import PdfReader


def extract_pdf(data: bytes) -> ExtractedText:
    """Return the text of the first pages; image-only pages give no text."""
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise TextExtractionError("encrypted pdf")
        chunks: list[str] = []
        total = 0
        for page in reader.pages[:MAX_PDF_PAGES]:
            text = page.extract_text() or ""
            chunks.append(text)
            total += len(text)
            if total >= MAX_TEXT_CHARS:
                break
        pages = len(reader.pages)
    except TextExtractionError:
        raise
    except Exception as exc:  # pypdf raises many types for damaged files
        raise TextExtractionError(f"pdf: {exc}") from exc
    return ExtractedText(text="\n".join(chunks)[:MAX_TEXT_CHARS], pages=pages)
