"""Buttons as plain dicts (the format of RenderedMessage) and their conversion."""

from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

Button = dict[str, Any]
Rows = list[list[Button]]

NONE_DATA = "none"


def cb_button(text: str, data: CallbackData) -> Button:
    """Button that sends callback data."""
    return {"text": text, "callback_data": data.pack()}


def none_button(text: str) -> Button:
    """Label-like button that does nothing when pressed."""
    return {"text": text, "callback_data": NONE_DATA}


def url_button(text: str, url: str) -> Button:
    """Button that opens a link."""
    return {"text": text, "url": url}


def web_app_button(text: str, url: str) -> Button:
    """Button that opens a mini app (inline web_app buttons give initData)."""
    return {"text": text, "web_app_url": url}


def _convert(button: Button) -> InlineKeyboardButton:
    text = str(button["text"])
    if "callback_data" in button:
        return InlineKeyboardButton(text=text, callback_data=button["callback_data"])
    if "web_app_url" in button:
        return InlineKeyboardButton(
            text=text, web_app=WebAppInfo(url=button["web_app_url"])
        )
    return InlineKeyboardButton(text=text, url=button["url"])


def to_markup(rows: Rows | None) -> InlineKeyboardMarkup | None:
    """Convert button dicts to an inline keyboard (None for no buttons)."""
    if not rows:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[_convert(button) for button in row] for row in rows if row]
    )


def pairs(buttons: list[Button], per_row: int = 2) -> Rows:
    """Lay buttons out in rows of ``per_row``."""
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def toggle_text(label: str, enabled: bool) -> str:
    """Prefix a label with a check box that shows whether the option is on."""
    return f"{'✅' if enabled else '⬜'} {label}"
