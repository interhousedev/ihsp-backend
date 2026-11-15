"""The lyceum logo Administration uploads: PNG, JPEG or WebP, at most 1 MiB."""

from dataclasses import dataclass
from typing import Any

from app.shared.base_error import NotFoundError, ValidationFailedError

SETTING_KEY = "lyceum_logo"
MAX_LOGO_BYTES = 1024 * 1024
URL_VERSION_LENGTH = 12
PUBLIC_PATH = "/v1/public/lyceum-logo"


class LogoTypeNotAllowedError(ValidationFailedError):
    """The logo is not a PNG, JPEG or WebP image."""

    code = "admin/logo-type-not-allowed"
    message_key = "admin-logo-type-not-allowed"


class LogoTooLargeError(ValidationFailedError):
    """The logo is bigger than the limit; ``params.max_kb`` says how much."""

    code = "admin/logo-too-large"
    status = 413
    message_key = "admin-logo-too-large"


class LogoNotFoundError(NotFoundError):
    """No logo has been uploaded."""

    code = "admin/logo-not-found"
    message_key = "admin-logo-not-found"


@dataclass(frozen=True, slots=True)
class LyceumLogo:
    """Where the logo lives in object storage and what it is."""

    object_key: str
    sha256: str
    content_type: str

    @property
    def url(self) -> str:
        """API-relative public link; the version busts caches on a new upload."""
        return f"{PUBLIC_PATH}?v={self.sha256[:URL_VERSION_LENGTH]}"

    def as_stored(self) -> dict[str, Any]:
        """The JSON value kept in ``admin.platform_settings``."""
        return {
            "object_key": self.object_key,
            "sha256": self.sha256,
            "content_type": self.content_type,
        }


def logo_from_stored(value: Any) -> LyceumLogo | None:
    """Parse the stored value; anything broken counts as no logo."""
    if not isinstance(value, dict):
        return None
    key, digest, ctype = (
        value.get("object_key"),
        value.get("sha256"),
        value.get("content_type"),
    )
    if not (
        isinstance(key, str)
        and key
        and isinstance(digest, str)
        and digest
        and isinstance(ctype, str)
        and ctype
    ):
        return None
    return LyceumLogo(key, digest, ctype)


def sniff_logo(data: bytes) -> str:
    """Return the content type from the magic bytes; the declared type never counts.

    The size is checked first so an oversized upload read up to one byte over the
    limit is told apart from a wrong type. SVG is refused on purpose (it would run
    scripts from the API origin).
    """
    if len(data) > MAX_LOGO_BYTES:
        raise LogoTooLargeError(params={"max_kb": MAX_LOGO_BYTES // 1024})
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise LogoTypeNotAllowedError()
