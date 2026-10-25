"""Text of PDF files (pypdf, pure Python; blocking)."""

import io

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction.limits import (
    MAX_PDF_PAGES,
    MAX_TEXT_CHARS,
)
from app.modules.files.infrastructure.extraction.pdf_outline import read_pdf_outline
from app.modules.files.ports.text_extractor import ExtractedText

from pypdf import PdfReader


def extract_pdf(data: bytes) -> ExtractedText:
    """Return the text of the first pages, where each page starts, and the bookmarks.

    Image-only pages give no text. NUL characters (PostgreSQL cannot store them)
    are removed per page, so the page offsets stay right in the final text; offsets
    of pages cut off by ``MAX_TEXT_CHARS`` are dropped.
    """
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise TextExtractionError("encrypted pdf")
        chunks: list[str] = []
        starts: list[int] = []
        total = 0
        position = 0
        for page in reader.pages[:MAX_PDF_PAGES]:
            text = (page.extract_text() or "").replace("\x00", "")
            chunks.append(text)
            starts.append(position)
            position += len(text) + 1  # the newline that joins the pages
            total += len(text)
            if total >= MAX_TEXT_CHARS:
                break
        pages = len(reader.pages)
        outline = read_pdf_outline(reader)
    except TextExtractionError:
        raise
    except Exception as exc:  # pypdf raises many types for damaged files
        raise TextExtractionError(f"pdf: {exc}") from exc
    joined = "\n".join(chunks)
    if len(joined) > MAX_TEXT_CHARS:
        starts = [start for start in starts if start < MAX_TEXT_CHARS]
    return ExtractedText(
        text=joined[:MAX_TEXT_CHARS],
        pages=pages,
        page_starts=tuple(starts),
        outline=outline,
    )
