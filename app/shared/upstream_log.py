"""Safe description of an upstream answer for logs.

Status, content type and length are always logged. The body is logged only when
it parses as JSON, after key-based redaction, cut to 2 KB. Anything else (an
HTML login page, a truncated or malformed document) is replaced by a marker.
"""

import json
import re
from typing import Any
from urllib.parse import urlsplit

MAX_BODY_BYTES = 2048
_READ_LIMIT = 16 * 1024  # never parse a bigger download for a log line
_SECRET_KEY = re.compile(
    r"token|access|refresh|password|secret|key|otp|code|authorization|cookie"
    r"|session|csrf|pinfl|passport|login|phone|name",
    re.I,
)
_BEARER = re.compile(r"\bBearer\s+\S+", re.I)
REDACTED = "[redacted]"


def _redact(value: Any) -> Any:
    """Copy of parsed JSON with the value of every secret-looking key hidden."""
    if isinstance(value, dict):
        return {
            key: REDACTED if _SECRET_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        if value.lstrip()[:1] in ("{", "["):
            try:
                return _redact(json.loads(value))
            except (ValueError, RecursionError):
                return REDACTED  # malformed JSON in a string: cannot be vetted
        if _BEARER.search(value):
            return REDACTED
    return value


def log_body(
    content: bytes, content_type: str | None = None, limit: int = MAX_BODY_BYTES
) -> str:
    """A redacted JSON body cut to ``limit`` chars, else a marker without content."""
    size = len(content)
    if size > _READ_LIMIT:
        return f"<body {size} bytes>"
    try:
        parsed = json.loads(content)
    except (ValueError, RecursionError):
        kind = "html" if looks_like_html(content_type, content) else "non-json"
        return f"<{kind} {size} bytes>"
    try:
        text = json.dumps(_redact(parsed), ensure_ascii=False)
    except RecursionError:
        return f"<json {size} bytes>"
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def body_fields(content: bytes, content_type: str | None) -> dict[str, Any]:
    """Log fields describing an upstream body: type, length and safe body."""
    return {
        "content_type": content_type,
        "length": len(content),
        "body": log_body(content, content_type),
    }


def url_path(url: str) -> str:
    """The path of a URL: no host, no query string (it may carry secrets)."""
    return urlsplit(url).path or "/"


def looks_like_html(content_type: str | None, content: bytes) -> bool:
    """True for a login page or an error page where JSON was expected."""
    if content_type and "html" in content_type.lower():
        return True
    head = content[:256].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html"))
