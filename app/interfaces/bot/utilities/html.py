"""Helpers for Telegram's HTML subset."""

import html
import re

_TAG = re.compile(r"<[^>]*>")


def escape(value: str) -> str:
    """Escape ``& < >`` so user text can be placed inside a message."""
    return html.escape(value, quote=False)


def bold(value: str) -> str:
    """Return the escaped value in bold."""
    return f"<b>{escape(value)}</b>"


def code(value: str) -> str:
    """Return the escaped value as inline code."""
    return f"<code>{escape(value)}</code>"


def visible_length(markup: str) -> int:
    """Return the length Telegram counts: characters after entity parsing."""
    return len(html.unescape(_TAG.sub("", markup)))


def shorten(value: str, limit: int) -> str:
    """Cut a plain string to ``limit`` characters, adding an ellipsis."""
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
