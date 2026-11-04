"""Telegram rejects HTML it cannot parse: the answer then goes out as plain text."""

import html as html_lib
import re

from app.interfaces.bot.richtext.inline import escape

from aiogram.exceptions import TelegramBadRequest

_TAG = re.compile(r"<[^>]+>")
_MARKUP_ERRORS = (
    "can't parse",
    "can't find end tag",
    "unsupported start tag",
    "unsupported end tag",
    "unclosed",
)


def is_markup_error(error: BaseException) -> bool:
    """True when Telegram refused the text because its HTML is not valid."""
    if not isinstance(error, TelegramBadRequest):
        return False
    message = error.message.lower()
    return any(marker in message for marker in _MARKUP_ERRORS)


def plain_fallback(html: str) -> str:
    """The HTML message as escaped plain text: the words stay, the markup goes."""
    return escape(html_lib.unescape(_TAG.sub("", html)))
