"""FILE-7: text extraction from PDF, DOCX, TXT and MD (real pypdf and python-docx)."""

import io
import zipfile

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction import docx_text
from app.modules.files.infrastructure.extraction.extractor import FileTextExtractor
from tests.files.helpers import DOCX_TYPE, PDF_TYPE, make_docx, make_pdf

import pytest


@pytest.fixture
def extractor() -> FileTextExtractor:
    """The real extractor."""
    return FileTextExtractor()


def test_the_extractor_supports_exactly_the_text_types(
    extractor: FileTextExtractor,
) -> None:
    """PDF, DOCX, TXT, MD; nothing else."""
    for supported in (PDF_TYPE, DOCX_TYPE, "text/plain", "text/markdown"):
        assert extractor.supports(supported)
    for other in ("image/png", "application/octet-stream", "text/html"):
        assert not extractor.supports(other)


async def test_pdf_text_and_page_count(extractor: FileTextExtractor) -> None:
    """pypdf: text of every page and the number of pages."""
    result = await extractor.extract(PDF_TYPE, make_pdf("Alpha beta", "Gamma delta"))

    assert "Alpha beta" in result.text
    assert "Gamma delta" in result.text
    assert result.pages == 2


async def test_garbage_pdf_raises_extraction_error(
    extractor: FileTextExtractor,
) -> None:
    """Damaged files raise the module's own error, never a pypdf one."""
    with pytest.raises(TextExtractionError):
        await extractor.extract(PDF_TYPE, b"%PDF-1.4 not really")


async def test_docx_paragraphs_and_table_rows(extractor: FileTextExtractor) -> None:
    """python-docx: paragraphs then table rows, cells joined by tabs."""
    data = make_docx("First", "Second", table=[["a", "b"], ["c", "d"]])

    result = await extractor.extract(DOCX_TYPE, data)

    assert result.text.splitlines() == ["First", "Second", "a\tb", "c\td"]
    assert result.pages is None


async def test_a_zip_that_is_not_a_docx_raises_extraction_error(
    extractor: FileTextExtractor,
) -> None:
    """A plain zip has no [Content_Types].xml."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.txt", "hello")

    with pytest.raises(TextExtractionError):
        await extractor.extract(DOCX_TYPE, buffer.getvalue())


async def test_a_zip_with_too_many_parts_is_refused_before_unpacking(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zip-bomb guard: entry count and unpacked size are capped."""
    monkeypatch.setattr(docx_text, "MAX_ZIP_ENTRIES", 2)

    with pytest.raises(TextExtractionError, match="too many parts"):
        await extractor.extract(DOCX_TYPE, make_docx("hello"))


async def test_a_zip_that_unpacks_too_large_is_refused(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absolute cap on the unpacked size."""
    monkeypatch.setattr(docx_text, "MAX_ZIP_UNCOMPRESSED", 100)

    with pytest.raises(TextExtractionError, match="too large"):
        await extractor.extract(DOCX_TYPE, make_docx("hello"))


async def test_plain_text_drops_the_bom_and_nul_bytes(
    extractor: FileTextExtractor,
) -> None:
    """PostgreSQL cannot store NUL; a UTF-8 BOM is not text."""
    data = b"\xef\xbb\xbfhello\x00 world"

    result = await extractor.extract("text/plain", data)

    assert result.text == "hello world"


async def test_markdown_is_read_like_plain_text(extractor: FileTextExtractor) -> None:
    """MD files are text."""
    result = await extractor.extract("text/markdown", "# Заголовок".encode())

    assert result.text == "# Заголовок"
