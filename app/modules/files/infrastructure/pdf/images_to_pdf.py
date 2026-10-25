"""Write one PDF with a page per photo (pure Python, no image library).

JPEG and simple PNG data go into the file untouched (see ``image_info``), so this is
fast and loses nothing. A page is as wide as A4 (595 pt) and as tall as the image
needs, so a photo of a worksheet is read at the same size as any other page.
"""

from collections.abc import Sequence

from app.modules.files.infrastructure.pdf.image_info import PdfImage, read_image

A4_WIDTH = 595.0
MAX_PAGE_POINTS = 14400.0  # the PDF 1.x limit of a page side (200 inches)
_HEADER = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
_OBJECTS_PER_PAGE = 3  # page, content stream, image


def images_to_pdf(images: Sequence[bytes]) -> bytes:
    """Return the PDF of the images, one page each, in the given order.

    Raises:
        ValueError: There are no images.
        ImageNotSupportedError: An image is not a plain JPEG or PNG.
    """
    if not images:
        raise ValueError("no images to put into a PDF")
    pictures = [read_image(data) for data in images]
    objects = _catalog(len(pictures))
    for index, picture in enumerate(pictures):
        objects.extend(_page_objects(index, picture))
    return _serialize(objects)


class PureImagePdfBuilder:
    """``ImagePdfBuilder`` without third-party libraries."""

    def build(self, images: Sequence[bytes]) -> bytes:
        """Return the PDF of the images."""
        return images_to_pdf(images)


def _number(value: float) -> str:
    """Format a length in points."""
    return f"{value:.2f}"


def _page_size(picture: PdfImage) -> tuple[float, float]:
    """The media box (stored orientation) so that the shown page is A4 wide."""
    sideways = picture.rotate in {90, 270}
    shown_width = picture.height if sideways else picture.width
    shown_height = picture.width if sideways else picture.height
    scale = min(A4_WIDTH / shown_width, MAX_PAGE_POINTS / shown_height)
    return picture.width * scale, picture.height * scale


def _catalog(pages: int) -> list[bytes]:
    """Objects 1 (catalog) and 2 (page tree); pages are objects 3, 6, 9, ..."""
    first = 3
    kids = " ".join(f"{first + _OBJECTS_PER_PAGE * n} 0 R" for n in range(pages))
    return [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
    ]


def _stream(entries: str, data: bytes) -> bytes:
    """A stream object: dictionary entries, then the data."""
    head = f"<< {entries}/Length {len(data)} >>\nstream\n".encode()
    return head + data + b"\nendstream"


def _page_objects(index: int, picture: PdfImage) -> list[bytes]:
    """The page, its content stream and its image."""
    first = 3 + _OBJECTS_PER_PAGE * index
    width, height = _page_size(picture)
    rotate = f"/Rotate {picture.rotate} " if picture.rotate else ""
    page = (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_number(width)} "
        f"{_number(height)}] {rotate}"
        f"/Resources << /XObject << /Im0 {first + 2} 0 R >> >> "
        f"/Contents {first + 1} 0 R >>"
    ).encode()
    content = f"q {_number(width)} 0 0 {_number(height)} 0 0 cm /Im0 Do Q\n".encode()
    image = _stream(
        f"/Type /XObject /Subtype /Image /Width {picture.width} "
        f"/Height {picture.height} /ColorSpace {picture.color_space} "
        f"/BitsPerComponent 8 /Filter {picture.filter} {picture.extra}",
        picture.data,
    )
    return [page, _stream("", content), image]


def _serialize(objects: list[bytes]) -> bytes:
    """Write the numbered objects, the cross-reference table and the trailer."""
    out = bytearray(_HEADER)
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)
