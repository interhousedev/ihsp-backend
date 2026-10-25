"""LIB-5 (files part): photos become one PDF, a page each, with no new dependency."""

import io
from collections.abc import Sequence
from typing import cast

from app.modules.files.domain.errors import ImageNotSupportedError
from app.modules.files.infrastructure.extraction.pdf_text import extract_pdf
from app.modules.files.infrastructure.pdf.images_to_pdf import images_to_pdf
from tests.files.helpers import make_jpeg, make_png

import pytest
from pypdf import PageObject, PdfReader
from pypdf.generic import DictionaryObject, StreamObject

A4_WIDTH = 595.0


def read(pdf: bytes) -> PdfReader:
    """Open the PDF strictly: a wrong cross-reference table fails here."""
    return PdfReader(io.BytesIO(pdf), strict=True)


def image_of(page: PageObject) -> StreamObject:
    """The one image XObject of a page."""
    resources = cast(DictionaryObject, page["/Resources"])
    xobjects = cast(DictionaryObject, resources["/XObject"])
    return cast(StreamObject, xobjects["/Im0"].get_object())


def plain(value: object) -> object:
    """Python value of a pypdf object (numbers, names, arrays, dictionaries)."""
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, bool | int | float):
        return value + 0 if not isinstance(value, bool) else value
    return str(value) if isinstance(value, str) else value


def box(page: PageObject) -> tuple[float, float]:
    """Width and height of the (unrotated) media box in points."""
    return float(page.mediabox.width), float(page.mediabox.height)


def test_one_rgb_jpeg_becomes_a_one_page_pdf_with_the_jpeg_embedded_as_is() -> None:
    """The JPEG is not re-encoded: same bytes under /DCTDecode."""
    jpeg = make_jpeg(400, 200)

    reader = read(images_to_pdf([jpeg]))

    assert len(reader.pages) == 1
    image = image_of(reader.pages[0])
    assert plain(image["/Filter"]) == "/DCTDecode"
    assert plain(image["/ColorSpace"]) == "/DeviceRGB"
    assert plain([image["/Width"], image["/Height"], image["/BitsPerComponent"]]) == [
        400,
        200,
        8,
    ]
    assert image.get_data() == jpeg
    assert box(reader.pages[0]) == (A4_WIDTH, 297.5)


@pytest.mark.parametrize(
    ("components", "space"),
    [(1, "/DeviceGray"), (3, "/DeviceRGB"), (4, "/DeviceCMYK")],
)
@pytest.mark.parametrize("marker", [0xC0, 0xC1, 0xC2])
def test_gray_rgb_and_cmyk_baseline_and_progressive_jpegs_are_accepted(
    components: int, space: str, marker: int
) -> None:
    """SOF0, SOF1 and SOF2 with 1, 3 or 4 components."""
    reader = read(
        images_to_pdf([make_jpeg(30, 20, components=components, marker=marker)])
    )

    assert plain(image_of(reader.pages[0])["/ColorSpace"]) == space


def test_a_cmyk_jpeg_is_inverted_back_with_a_decode_array() -> None:
    """Adobe CMYK JPEGs store inverted values: /Decode [1 0 1 0 1 0 1 0]."""
    reader = read(images_to_pdf([make_jpeg(30, 20, components=4)]))

    assert plain(image_of(reader.pages[0])["/Decode"]) == [1, 0, 1, 0, 1, 0, 1, 0]


def test_pages_follow_the_order_of_the_images() -> None:
    """Page n is image n (told apart by their aspect ratio)."""
    images = [make_jpeg(100, 100), make_jpeg(100, 200), make_jpeg(200, 100)]

    reader = read(images_to_pdf(images))

    assert [box(page) for page in reader.pages] == [
        (A4_WIDTH, A4_WIDTH),
        (A4_WIDTH, 2 * A4_WIDTH),
        (A4_WIDTH, A4_WIDTH / 2),
    ]


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((4000, 3000), (A4_WIDTH, 446.25)),  # a phone photo shrinks to A4 width
        ((10, 10), (A4_WIDTH, A4_WIDTH)),  # a tiny image fills the A4 width
        ((100, 60_000), (24.0, 14400.0)),  # a very tall strip is clamped
    ],
)
def test_the_page_fits_the_a4_width_within_the_pdf_size_limit(
    size: tuple[int, int], expected: tuple[float, float]
) -> None:
    """Width 595 pt keeping the aspect; never taller than 14 400 pt."""
    width, height = box(read(images_to_pdf([make_jpeg(*size)])).pages[0])

    assert (round(width, 2), round(height, 2)) == expected


@pytest.mark.parametrize(
    ("orientation", "rotate", "stored"),
    [(1, 0, (A4_WIDTH, 297.5)), (3, 180, (A4_WIDTH, 297.5)), (6, 90, (1190.0, 595.0))],
)
def test_the_exif_orientation_of_a_photo_turns_the_page(
    orientation: int, rotate: int, stored: tuple[float, float]
) -> None:
    """Phones store photos sideways: /Rotate shows them upright, no re-encoding."""
    reader = read(images_to_pdf([make_jpeg(400, 200, orientation=orientation)]))

    page = reader.pages[0]
    assert plain(page.get("/Rotate", 0)) == rotate
    assert box(page) == stored


def test_a_portrait_photo_stored_sideways_fits_the_a4_width_when_shown() -> None:
    """Orientation 8: stored 4000x3000, shown 3000 wide and 4000 high."""
    reader = read(images_to_pdf([make_jpeg(4000, 3000, orientation=8)]))

    page = reader.pages[0]
    assert plain(page["/Rotate"]) == 270
    shown_w, shown_h = box(page)[1], box(page)[0]
    assert (round(shown_w, 2), round(shown_h, 2)) == (A4_WIDTH, 793.33)


def test_little_endian_exif_is_read_too() -> None:
    """Some cameras write `II` instead of `MM`."""
    jpeg = make_jpeg(400, 200, orientation=6, little_endian=True)

    assert plain(read(images_to_pdf([jpeg])).pages[0]["/Rotate"]) == 90


@pytest.mark.parametrize(
    ("color_type", "space", "colors"), [(0, "/DeviceGray", 1), (2, "/DeviceRGB", 3)]
)
def test_gray_and_rgb_pngs_reuse_their_compressed_data(
    color_type: int, space: str, colors: int
) -> None:
    """The PNG's IDAT bytes go in as /FlateDecode with a PNG predictor."""
    png = make_png(8, 4, color_type=color_type)

    reader = read(images_to_pdf([png]))

    image = image_of(reader.pages[0])
    assert plain(image["/Filter"]) == "/FlateDecode"
    assert plain(image["/ColorSpace"]) == space
    assert plain(image["/DecodeParms"]) == {
        "/Predictor": 15,
        "/Colors": colors,
        "/Columns": 8,
        "/BitsPerComponent": 8,
    }
    assert image.get_data() == bytes(8 * 4 * colors)


def test_a_png_whose_data_is_split_over_several_idat_chunks_is_joined() -> None:
    """IDAT chunks are one zlib stream."""
    png = make_png(64, 64, idat_parts=3)

    image = image_of(read(images_to_pdf([png])).pages[0])

    assert image.get_data() == bytes(64 * 64 * 3)


def test_jpeg_and_png_can_be_mixed() -> None:
    """A scan from the phone and a screenshot."""
    reader = read(images_to_pdf([make_jpeg(10, 10), make_png(10, 10)]))

    filters = [plain(image_of(page)["/Filter"]) for page in reader.pages]
    assert filters == ["/DCTDecode", "/FlateDecode"]


def test_other_png_metadata_chunks_are_ignored() -> None:
    """Gamma, text, ... are not needed; the pixels are."""
    png = make_png(5, 5, chunks=[(b"gAMA", b"\x00\x00\xb1\x8f"), (b"tEXt", b"a\x00b")])

    assert len(read(images_to_pdf([png])).pages) == 1


def test_the_result_passes_the_text_extractor_without_text() -> None:
    """The library runs the same scan job on it as on any uploaded PDF."""
    pdf = images_to_pdf([make_jpeg(30, 30), make_png(30, 30)])

    result = extract_pdf(pdf)

    assert result.pages == 2
    assert result.text.strip() == ""


# - - - What cannot be embedded - - -


def unsupported(images: Sequence[bytes]) -> ImageNotSupportedError:
    """Run the assembler and return the error it must raise."""
    with pytest.raises(ImageNotSupportedError) as caught:
        images_to_pdf(images)
    return caught.value


@pytest.mark.parametrize(
    "png",
    [
        make_png(4, 4, color_type=3, chunks=[(b"PLTE", b"\x00" * 6)]),  # palette
        make_png(4, 4, color_type=4),  # gray with alpha
        make_png(4, 4, color_type=6),  # RGBA
        make_png(4, 4, bit_depth=16),
        make_png(4, 4, color_type=0, bit_depth=1),
        make_png(4, 4, interlace=1),
        make_png(4, 4, chunks=[(b"tRNS", b"\x00\x00\x00\x00\x00\x00")]),
    ],
    ids=["palette", "gray-alpha", "rgba", "16-bit", "1-bit", "interlaced", "trns"],
)
def test_pngs_that_need_decoding_are_refused_with_the_use_a_jpeg_message(
    png: bytes,
) -> None:
    """Alpha, palette, interlaced, 16-bit and colour-keyed PNGs: send a JPEG."""
    error = unsupported([png])

    assert error.status == 422
    assert error.message_key == "error-file-image-unsupported"
    assert error.code == "files/image-unsupported"


@pytest.mark.parametrize(
    "data",
    [
        b"GIF89a" + b"\x00" * 32,
        b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32,
        b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32,
        b"%PDF-1.4 not an image",
        b"",
        b"random bytes that are not an image at all",
    ],
    ids=["gif", "webp", "heic", "pdf", "empty", "random"],
)
def test_other_formats_are_refused(data: bytes) -> None:
    """Only JPEG and PNG, recognised by their bytes, not their file names."""
    unsupported([data])


@pytest.mark.parametrize(
    "jpeg",
    [
        make_jpeg(10, 10, marker=0xC3),  # lossless
        make_jpeg(10, 10, marker=0xC9),  # arithmetic coding
        make_jpeg(10, 10, precision=12),
        make_jpeg(10, 10, components=2),
        make_jpeg(0, 10),
        make_jpeg(10, 10)[:25],  # cut before the frame header
        b"\xff\xd8\xff\xe0\x00\x10JFIF",  # no frame header at all
    ],
    ids=[
        "lossless",
        "arithmetic",
        "12-bit",
        "2-components",
        "zero-width",
        "cut",
        "no-sof",
    ],
)
def test_jpegs_a_pdf_viewer_cannot_show_are_refused(jpeg: bytes) -> None:
    """Only baseline, extended and progressive 8-bit JPEGs with 1, 3 or 4 colours."""
    unsupported([jpeg])


@pytest.mark.parametrize(
    "png",
    [
        b"\x89PNG\r\n\x1a\n",  # nothing after the signature
        make_png(4, 4)[:40],  # cut inside the header chunk
        make_png(4, 4)[:-30],  # cut inside the data
        make_png(0, 4),
    ],
    ids=["bare", "cut-header", "cut-data", "zero-width"],
)
def test_damaged_pngs_are_refused(png: bytes) -> None:
    """A damaged file is not silently embedded."""
    unsupported([png])


def test_one_bad_image_refuses_the_whole_document() -> None:
    """No half documents."""
    unsupported([make_jpeg(10, 10), make_png(4, 4, color_type=6)])


def test_an_empty_list_is_a_programming_error() -> None:
    """Callers check the count (1 to 20) before building."""
    with pytest.raises(ValueError, match="no images"):
        images_to_pdf([])
