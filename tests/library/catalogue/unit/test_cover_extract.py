"""Cover images cut out of tiny generated PDF and EPUB files."""

import io
import zipfile

from app.modules.library.application.catalogue.cover_extract import extract_cover
from app.modules.library.domain.enums import FileFormat

import pypdfium2

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
    b"\x02\xfe\xa7\x9a\xdc\xd6\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _pdf() -> bytes:
    document = pypdfium2.PdfDocument.new()
    document.new_page(200, 300)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _epub(*, with_meta: bool) -> bytes:
    container = (
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'
    )
    meta = '<meta name="cover" content="c"/>' if with_meta else ""
    opf = (
        '<package xmlns="http://www.idpf.org/2007/opf"><metadata>'
        f"{meta}</metadata><manifest>"
        '<item id="a" href="images/a.png" media-type="image/png"/>'
        '<item id="c" href="images/cover.png" media-type="image/png"/>'
        "</manifest></package>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/images/a.png", PNG + b"a")
        archive.writestr("OEBPS/images/cover.png", PNG + b"c")
    return out.getvalue()


def test_pdf_first_page_becomes_a_jpeg() -> None:
    """The first page is rendered."""
    found = extract_cover(_pdf(), FileFormat.PDF)
    assert found is not None
    image, name = found
    assert name == "cover.jpg"
    assert image[:2] == b"\xff\xd8"


def test_epub_uses_the_cover_named_in_the_opf() -> None:
    """The OPF cover wins over the first image."""
    found = extract_cover(_epub(with_meta=True), FileFormat.EPUB)
    assert found == (PNG + b"c", "cover.png")


def test_epub_without_meta_uses_the_first_image() -> None:
    """No cover entry: first image in the archive."""
    found = extract_cover(_epub(with_meta=False), FileFormat.EPUB)
    assert found is not None
    assert found[0] == PNG + b"a"


def test_broken_or_unsupported_files_have_no_cover() -> None:
    """Garbage and text files give None."""
    assert extract_cover(b"%PDF-1.4", FileFormat.PDF) is None
    assert extract_cover(b"nope", FileFormat.EPUB) is None
    assert extract_cover(b"text", FileFormat.TXT) is None
