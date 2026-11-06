"""Third-party text in tool results: clean it, cap it, label it; never rewrite it.

This is not a security control by itself: authorization takes no input from content.
"""

import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

DEFAULT_MAX_LENGTH = 8192
_KEPT_CONTROLS = frozenset("\n\t")
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


def clean_text(value: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> str:
    """Drop control and invisible characters and cap the length."""
    cleaned = "".join(
        char
        for char in value
        if char in _KEPT_CONTROLS
        or unicodedata.category(char) not in _DROPPED_CATEGORIES
    )
    return cleaned if len(cleaned) <= max_length else f"{cleaned[:max_length]}…"


def mark_untrusted(
    result: Mapping[str, Any], *paths: str, max_length: int = DEFAULT_MAX_LENGTH
) -> dict[str, Any]:
    """Return a copy with these fields cleaned and listed in `untrusted_fields`.

    A path is `topic`, `lesson.topic` or `rows[].text`. Absent fields are fine.
    """
    copy = dict(result)
    for path in paths:
        copy = _clean_path(copy, path.split("."), max_length)
    copy["untrusted_fields"] = list(paths)
    return copy


def _clean_path(value: Any, parts: list[str], max_length: int) -> Any:  # noqa: ANN401
    if not parts:
        return (
            clean_text(value, max_length=max_length)
            if isinstance(value, str)
            else value
        )
    if not isinstance(value, Mapping):
        return value
    name, is_list = parts[0].removesuffix("[]"), parts[0].endswith("[]")
    if name not in value:
        return value
    child = value[name]
    if is_list and isinstance(child, list):
        cleaned: Any = [_clean_path(item, parts[1:], max_length) for item in child]
    else:
        cleaned = _clean_path(child, parts[1:], max_length)
    return {**value, name: cleaned}


def safe_external_url(url: str | None) -> str | None:
    """Return an http(s) address from content, or None; for `external_url` only.

    Such an address never goes into `links`, which holds our own URLs alone.
    """
    if not url or any(unicodedata.category(c) in _DROPPED_CATEGORIES for c in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    return url
