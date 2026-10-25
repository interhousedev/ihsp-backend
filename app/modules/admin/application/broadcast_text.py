"""Telegram-compatible HTML of broadcast texts: sanitising and length."""

import html
import re

from app.modules.admin.domain.errors import BroadcastTextTooLongError

import nh3

MAX_PLAIN_CHARS = 3800
"""Title and text together, after tags are removed (Telegram allows 4096)."""

_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "a",
    "code",
    "pre",
    "blockquote",
    "tg-spoiler",
    "span",
}
_ATTRIBUTES = {
    "a": {"href"},
    "span": {"class"},
    "code": {"class"},
    "blockquote": {"expandable"},
}
_SCHEMES = {"http", "https", "tg", "mailto"}
_BREAKS = re.compile(r"<br\s*/?>", re.IGNORECASE)
_PARAGRAPHS = re.compile(r"</(?:p|div)>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def sanitize_telegram_html(text: str) -> str:
    """Keep only the tags Telegram supports; turn <br> and paragraphs into newlines."""
    prepared = _PARAGRAPHS.sub("\n", _BREAKS.sub("\n", text))
    cleaned = nh3.clean(
        prepared,
        tags=_TAGS,
        attributes=_ATTRIBUTES,
        url_schemes=_SCHEMES,
        link_rel=None,
    )
    # Telegram knows only &lt; &gt; &amp; &quot; as named entities.
    return cleaned.replace("&nbsp;", "&#160;").strip()


def plain_length(text_html: str) -> int:
    """Length of the text as Telegram counts it (after entity parsing)."""
    return len(html.unescape(_TAG.sub("", text_html)))


def ensure_fits(title: str, text_html: str) -> None:
    """Raise BroadcastTextTooLongError when title and text exceed one message."""
    total = len(title) + plain_length(text_html)
    if total > MAX_PLAIN_CHARS:
        raise BroadcastTextTooLongError(
            params={"length": total, "limit": MAX_PLAIN_CHARS}
        )
