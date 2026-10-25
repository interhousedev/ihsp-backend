"""NB-SRC-FILE: character offsets of PDF pages in the extracted text (page_starts)."""

from app.modules.files.infrastructure.extraction import pdf_text
from app.modules.files.infrastructure.extraction.extractor import FileTextExtractor
from tests.files.helpers import DOCX_TYPE, PDF_TYPE, make_docx, make_pdf

import pytest


class FakePage:
    """A page whose text is fixed."""

    def __init__(self, text: str) -> None:
        """Store the text."""
        self.text = text

    def extract_text(self) -> str:
        """Return the text like pypdf."""
        return self.text


def reader_of(*texts: str) -> type:
    """A PdfReader replacement with pages of the given texts."""

    class Reader:
        """A reader of pages that are not encrypted."""

        is_encrypted = False

        def __init__(self, *_: object, **__: object) -> None:
            """Ignore the stream."""
            self.pages = [FakePage(text) for text in texts]

    return Reader


@pytest.fixture
def extractor() -> FileTextExtractor:
    """The real extractor."""
    return FileTextExtractor()


async def test_a_three_page_pdf_reports_where_every_page_starts(
    extractor: FileTextExtractor,
) -> None:
    """Offsets slice the joined text back into the pages."""
    data = make_pdf("Alpha one", "Beta two two", "Gamma three")

    result = await extractor.extract(PDF_TYPE, data)

    assert result.pages == 3
    assert len(result.page_starts) == 3 and result.page_starts[0] == 0
    ends = [*result.page_starts[1:], len(result.text) + 1]
    pages = [result.text[s : e - 1] for s, e in zip(result.page_starts, ends)]
    assert pages == ["Alpha one", "Beta two two", "Gamma three"]


async def test_an_empty_page_keeps_the_offsets_of_the_following_pages(
    extractor: FileTextExtractor,
) -> None:
    """A blank page still has a start; later pages are not shifted."""
    result = await extractor.extract(PDF_TYPE, make_pdf("One", "", "Three"))

    assert result.text == "One\n\nThree"
    assert result.page_starts == (0, 4, 5)


async def test_nul_characters_are_removed_without_shifting_the_offsets(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offsets are computed on the text as stored (PostgreSQL cannot hold NUL)."""
    monkeypatch.setattr(pdf_text, "PdfReader", reader_of("a\x00b\x00", "cd", "\x00e"))

    result = await extractor.extract(PDF_TYPE, b"%PDF")

    assert result.text == "ab\ncd\ne"
    assert result.page_starts == (0, 3, 6)
    assert [result.text[s] for s in result.page_starts] == ["a", "c", "e"]


async def test_offsets_beyond_the_text_limit_are_dropped(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pages that start after the MAX_TEXT_CHARS cut have no offset."""
    monkeypatch.setattr(pdf_text, "MAX_TEXT_CHARS", 10)
    monkeypatch.setattr(pdf_text, "PdfReader", reader_of("aaaa", "bbbbb", "cc"))

    result = await extractor.extract(PDF_TYPE, b"%PDF")

    assert result.text == "aaaa\nbbbbb"
    assert result.page_starts == (0, 5)
    assert result.pages == 3  # the real page count is still reported


async def test_pages_after_the_limit_are_not_read_at_all(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading stops once the limit is reached, as before."""
    monkeypatch.setattr(pdf_text, "MAX_TEXT_CHARS", 8)
    monkeypatch.setattr(pdf_text, "PdfReader", reader_of("a" * 10, "bbb", "ccc"))

    result = await extractor.extract(PDF_TYPE, b"%PDF")

    assert result.text == "a" * 8
    assert result.page_starts == (0,)


async def test_documents_without_pages_have_no_offsets(
    extractor: FileTextExtractor,
) -> None:
    """DOCX, TXT and MD give an empty tuple."""
    docx = await extractor.extract(DOCX_TYPE, make_docx("Hello", "World"))
    plain = await extractor.extract("text/plain", b"hello")

    assert docx.page_starts == () and plain.page_starts == ()
