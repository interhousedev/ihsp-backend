"""Validation of the `[[button:Label|target]]` markup and Telegram button limits."""

import re
from urllib.parse import urlsplit

from app.interfaces.bot.richtext.model import ButtonSpec

CALLBACK_DATA_MAX_BYTES = 64
URL_MAX_LENGTH = 512

_BUTTON_LINE = re.compile(r"^\s*\[\[button:(.*)\]\]\s*$")
_NON_CALLBACK_TARGET = re.compile(r"://|^(javascript|data|tg|mailto):", re.IGNORECASE)


def match_button_line(line: str) -> str | None:
    """Return the body of a complete button line, or None if the line is not one.

    Args:
        line: One line of markdown.

    Returns:
        The text between `[[button:` and `]]`.
    """
    match = _BUTTON_LINE.fullmatch(line)
    return match.group(1) if match else None


def callback_data_fits(data: str) -> bool:
    """Check that callback data is non-empty and fits Telegram's 64-byte limit.

    Args:
        data: Callback data to send with a button.

    Returns:
        True when the UTF-8 encoding has 1 to 64 bytes.
    """
    return 0 < len(data.encode("utf-8")) <= CALLBACK_DATA_MAX_BYTES


def is_https_url(url: str) -> bool:
    """Check that a URL is an https URL with a host and no whitespace.

    Args:
        url: Candidate link target.

    Returns:
        True when the URL may be used in a link or a button.
    """
    if len(url) > URL_MAX_LENGTH or any(ch.isspace() for ch in url):
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.hostname)


def parse_button_body(body: str) -> ButtonSpec | None:
    """Parse `Label|target` into a button; the target is an https URL or callback data.

    Args:
        body: Text between `[[button:` and `]]`.

    Returns:
        The button, or None when the label or target is missing or not allowed.
    """
    label, separator, target = body.partition("|")
    label = label.strip()
    target = target.strip()
    if not separator or not label or not target:
        return None
    if target.lower().startswith("https://") or "://" in target:
        return ButtonSpec(label=label, url=target) if is_https_url(target) else None
    if _NON_CALLBACK_TARGET.search(target) or not callback_data_fits(target):
        return None
    return ButtonSpec(label=label, callback_data=target)
