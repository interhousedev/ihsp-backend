"""Rules for the photo of a user's profile: JPEG or PNG, at most 5 MiB."""

from dataclasses import dataclass

from app.modules.identity.domain.errors import (
    PhotoEmptyError,
    PhotoTooLargeError,
    PhotoTypeNotAllowedError,
)

MAX_PHOTO_BYTES = 5 * 1024 * 1024
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True, slots=True)
class PhotoFormat:
    """What a valid photo turned out to be."""

    extension: str  # without the dot: "jpg" or "png"
    content_type: str


JPEG = PhotoFormat(extension="jpg", content_type="image/jpeg")
PNG = PhotoFormat(extension="png", content_type="image/png")


def check_photo(data: bytes) -> PhotoFormat:
    """Return the format of the image or raise a domain error.

    Only the bytes count: the file name and the declared content type are never
    trusted. The size is checked first, so an oversized upload is told apart from a
    wrong type even when the caller read just ``MAX_PHOTO_BYTES + 1`` bytes of it.
    """
    if not data:
        raise PhotoEmptyError()
    if len(data) > MAX_PHOTO_BYTES:
        raise PhotoTooLargeError(params={"max_mb": MAX_PHOTO_BYTES // (1024 * 1024)})
    if data.startswith(_JPEG_MAGIC):
        return JPEG
    if data.startswith(_PNG_MAGIC):
        return PNG
    raise PhotoTypeNotAllowedError()
