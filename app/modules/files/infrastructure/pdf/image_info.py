"""Read the headers of a JPEG or PNG: what a PDF needs to embed it as it is.

Nothing is decoded or re-encoded. A JPEG goes into the PDF whole (/DCTDecode); a PNG
goes in as its own compressed data (/FlateDecode with a PNG predictor), which works
for non-interlaced 8-bit grayscale and RGB without transparency. Everything else
would need real image processing and is refused: the user is asked to send a JPEG.
"""

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass

from app.modules.files.domain.errors import ImageNotSupportedError

JPEG_START = b"\xff\xd8\xff"
PNG_START = b"\x89PNG\r\n\x1a\n"

_BASELINE_AND_PROGRESSIVE = frozenset({0xC0, 0xC1, 0xC2})
# every other start-of-frame marker: lossless, hierarchical or arithmetic coding
_OTHER_FRAMES = (
    frozenset(range(0xC0, 0xD0)) - _BASELINE_AND_PROGRESSIVE - {0xC4, 0xC8, 0xCC}
)
_NO_LENGTH = frozenset(range(0xD0, 0xD8)) | {0x01}  # RSTn and TEM
_START_OF_SCAN, _END_OF_IMAGE, _APP1 = 0xDA, 0xD9, 0xE1
_JPEG_SPACES = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}
_PNG_COLORS = {0: ("/DeviceGray", 1), 2: ("/DeviceRGB", 3)}
_ROTATE = {3: 180, 6: 90, 8: 270}  # EXIF orientation -> clockwise turn to show upright
_EXIF_ORIENTATION_TAG = 0x0112
_MAX_EXIF_ENTRIES = 64
_CMYK_DECODE = "/Decode [1 0 1 0 1 0 1 0] "  # Adobe CMYK JPEGs are stored inverted


@dataclass(frozen=True, slots=True)
class PdfImage:
    """An image ready to be written as a PDF image XObject."""

    width: int
    height: int
    color_space: str
    filter: str
    data: bytes
    extra: str = ""  # more entries of the image dictionary
    rotate: int = 0  # page rotation that shows the image upright


def read_image(data: bytes) -> PdfImage:
    """Return the image by its bytes; raise ImageNotSupportedError if not possible."""
    if data.startswith(JPEG_START):
        return _read_jpeg(data)
    if data.startswith(PNG_START):
        return _read_png(data)
    raise ImageNotSupportedError(support_details="not a JPEG or PNG file")


def _refuse(reason: str) -> ImageNotSupportedError:
    return ImageNotSupportedError(support_details=reason)


# - - - JPEG - - -


def _segments(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield ``(marker, payload)`` of the segments in front of the first scan."""
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            raise _refuse("damaged JPEG")
        marker = data[position + 1]
        if marker == 0xFF:  # fill byte
            position += 1
        elif marker in _NO_LENGTH:
            position += 2
        elif marker in {_START_OF_SCAN, _END_OF_IMAGE}:
            return
        else:
            length = struct.unpack(">H", data[position + 2 : position + 4])[0]
            end = position + 2 + length
            if length < 2 or end > len(data):
                raise _refuse("damaged JPEG")
            yield marker, data[position + 4 : end]
            position = end


def _read_jpeg(data: bytes) -> PdfImage:
    """Find the frame header (and the EXIF orientation before it)."""
    orientation = 1
    for marker, segment in _segments(data):
        if marker == _APP1:
            orientation = _exif_orientation(segment) or orientation
        elif marker in _OTHER_FRAMES:
            raise _refuse(f"JPEG coding {marker:#04x} cannot be embedded")
        elif marker in _BASELINE_AND_PROGRESSIVE:
            return _jpeg_image(data, segment, orientation)
    raise _refuse("JPEG without a frame header")


def _jpeg_image(data: bytes, frame: bytes, orientation: int) -> PdfImage:
    """Build the image from the frame header: precision, height, width, colours."""
    if len(frame) < 6:
        raise _refuse("damaged JPEG")
    precision, height, width, components = struct.unpack(">BHHB", frame[:6])
    if precision != 8 or not width or not height or components not in _JPEG_SPACES:
        raise _refuse("JPEG precision or colours cannot be embedded")
    return PdfImage(
        width=width,
        height=height,
        color_space=_JPEG_SPACES[components],
        filter="/DCTDecode",
        data=data,
        extra=_CMYK_DECODE if components == 4 else "",
        rotate=_ROTATE.get(orientation, 0),
    )


def _exif_orientation(segment: bytes) -> int | None:
    """Return the EXIF orientation (1 to 8) of an APP1 segment, if it has one."""
    if not segment.startswith(b"Exif\x00\x00") or len(segment) < 20:
        return None
    tiff = segment[6:]
    order = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if order is None:
        return None
    (first,) = struct.unpack_from(order + "I", tiff, 4)
    if first + 2 > len(tiff):
        return None
    (count,) = struct.unpack_from(order + "H", tiff, first)
    for index in range(min(count, _MAX_EXIF_ENTRIES)):
        at = first + 2 + 12 * index
        if at + 12 > len(tiff):
            return None
        tag, kind, items = struct.unpack_from(order + "HHI", tiff, at)
        if tag == _EXIF_ORIENTATION_TAG and kind == 3 and items == 1:
            return int(struct.unpack_from(order + "H", tiff, at + 8)[0])
    return None


# - - - PNG - - -


def _read_png(data: bytes) -> PdfImage:
    """Collect the header and the image data chunks, refusing what needs decoding."""
    position = len(PNG_START)
    header: tuple[int, int, int, int, int] | None = None
    parts: list[bytes] = []
    ended = False
    while position + 8 <= len(data) and not ended:
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        end = position + 8 + length
        if end + 4 > len(data):
            raise _refuse("PNG is cut short")
        payload = data[position + 8 : end]
        if kind == b"IHDR" and length == 13:
            width, height, depth, color, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            header = (width, height, depth, color, interlace)
        elif kind == b"tRNS":
            raise _refuse("PNG with transparency")
        elif kind == b"IDAT":
            parts.append(payload)
        ended = kind == b"IEND"
        position = end + 4
    if header is None or not parts or not ended:
        raise _refuse("PNG is damaged")
    return _png_image(header, b"".join(parts))


def _png_image(header: tuple[int, int, int, int, int], pixels: bytes) -> PdfImage:
    """Build the image from the header and the joined compressed data."""
    width, height, depth, color, interlace = header
    if depth != 8 or color not in _PNG_COLORS or interlace or not width or not height:
        raise _refuse("PNG needs decoding: use a JPEG")
    space, colors = _PNG_COLORS[color]
    _check_flate(pixels, height * (1 + width * colors))
    return PdfImage(
        width=width,
        height=height,
        color_space=space,
        filter="/FlateDecode",
        data=pixels,
        extra=(
            f"/DecodeParms << /Predictor 15 /Colors {colors} /Columns {width} "
            "/BitsPerComponent 8 >> "
        ),
    )


def _check_flate(pixels: bytes, expected: int) -> None:
    """The compressed data must hold exactly the rows the header promises."""
    unpacker = zlib.decompressobj()
    try:
        out = unpacker.decompress(pixels, expected + 1)
    except zlib.error as exc:
        raise _refuse(f"PNG data is damaged: {exc}") from exc
    if len(out) != expected or not unpacker.eof:
        raise _refuse("PNG data does not fit its header")
