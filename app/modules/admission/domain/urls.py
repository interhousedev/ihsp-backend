"""Link checks shared by the catalog and the checklist."""

from typing import Any, Final
from urllib.parse import urlsplit

URL_MAX_LENGTH: Final = 2000
_FORBIDDEN: Final = frozenset("\"'()\\")


def is_https_url(value: Any) -> bool:
    """True for a plain https address of sane length, safe to embed in markup."""
    if not isinstance(value, str) or len(value) > URL_MAX_LENGTH:
        return False
    if any(c in _FORBIDDEN or c.isspace() for c in value):
        return False
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.hostname)
