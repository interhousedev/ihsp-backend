"""Text helpers for notification titles and Telegram HTML."""

import html
import re
from datetime import date, datetime
from typing import Any

from app.shared.clock import to_local

_BREAKS = re.compile(r"<br\s*/?>|</p>|</div>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


def esc(value: object) -> str:
    """Escape text for Telegram HTML (&, < and > only)."""
    return html.escape(str(value), quote=False)


def esc_attr(value: object) -> str:
    """Escape text for a Telegram HTML attribute value."""
    return html.escape(str(value), quote=True)


def strip_html(value: str) -> str:
    """Turn Telegram HTML into plain text for the web notification center."""
    text = _BREAKS.sub("\n", value)
    text = _TAGS.sub("", text)
    return html.unescape(text).strip()


def _parse(value: Any) -> datetime | date | None:
    if isinstance(value, datetime | date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def fmt_date(value: Any) -> str:
    """Format a date or ISO string as dd.mm (the payload keeps the original)."""
    parsed = _parse(value)
    if parsed is None:
        return "" if value is None else str(value)
    return parsed.strftime("%d.%m")


def fmt_datetime(value: Any) -> str:
    """Format an aware datetime or ISO string as dd.mm.yyyy HH:MM in Tashkent."""
    parsed = _parse(value)
    if parsed is None:
        return "" if value is None else str(value)
    if isinstance(parsed, datetime):
        if parsed.tzinfo is not None:
            parsed = to_local(parsed)
        return parsed.strftime("%d.%m.%Y %H:%M")
    return parsed.strftime("%d.%m.%Y")


def fmt_number(value: Any) -> str:
    """Show floats with two decimals and everything else as it is."""
    if isinstance(value, float):
        return f"{value:.2f}"
    return "" if value is None else str(value)


def join_names(value: Any) -> str:
    """Join a list of names with commas; accept a single string too."""
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value)
    return "" if value is None else str(value)
