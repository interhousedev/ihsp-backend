"""Rules for a face image: JPEG or PNG, at most 5 MiB and 25 megapixels."""

import struct

from app.modules.faces.domain.errors import (
    FaceImageEmptyError,
    FaceImageTooLargeError,
    FaceImageTypeError,
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_TYPES = frozenset({"image/jpeg", "image/png"})
SNIFF_BYTES = 4096
MAX_PIXELS = 25_000_000
MAX_SIDE = 8000
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _png_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR" or len(data) < 24:
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker in _SOF_MARKERS:
            if pos + 9 > len(data):
                return None
            height, width = struct.unpack(">HH", data[pos + 5 : pos + 9])
            return int(width), int(height)
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            pos += 2
            continue
        pos += 2 + struct.unpack(">H", data[pos + 2 : pos + 4])[0]
    return None


def image_size(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) read from the PNG or JPEG header, if it parses."""
    return _png_size(data) or _jpeg_size(data)


def check_image(data: bytes, sniffed_type: str) -> None:
    """Raise a domain error unless the bytes are a non-empty JPEG or PNG in limits.

    The size is judged first so that callers who read just `MAX_IMAGE_BYTES + 1`
    bytes still get "too large" rather than "wrong type".
    """
    if not data:
        raise FaceImageEmptyError()
    if len(data) > MAX_IMAGE_BYTES:
        raise FaceImageTooLargeError(params={"max_mb": MAX_IMAGE_BYTES // 1024 // 1024})
    if sniffed_type not in ALLOWED_TYPES:
        raise FaceImageTypeError()
    size = image_size(data)
    if size is not None and (max(size) > MAX_SIDE or size[0] * size[1] > MAX_PIXELS):
        raise FaceImageTooLargeError(params={"max_mb": MAX_IMAGE_BYTES // 1024 // 1024})
