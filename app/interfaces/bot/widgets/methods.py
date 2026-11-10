"""Bot API 10.4 widget methods, which aiogram 3.31 does not ship yet.

Thin `TelegramMethod` subclasses: aiogram serialises the fields as the request
body, so nothing else is needed. Replace them by the library's own once it has them.
"""

from typing import Any

from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message


class SendWidget(TelegramMethod[Message]):
    """`sendWidget`: an HTML/CSS/JS widget in a private chat (returns the message)."""

    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: int
    html: str
    caption: str | None = None
    width: int | None = None
    height: int | None = None
    public_data: str | None = None
    chat_data: str | None = None
    allow_queries: bool | None = None
    disable_notification: bool | None = None
    reply_markup: InlineKeyboardMarkup | None = None


class AnswerWidgetQuery(TelegramMethod[bool]):
    """`answerWidgetQuery`: must answer every query within 15 seconds."""

    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    data: str | None = None


class EditMessageWidgetData(TelegramMethod[Any]):
    """`editMessageWidgetData`: change the state strings of a sent widget."""

    __returning__ = Any
    __api_method__ = "editMessageWidgetData"

    chat_id: int | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    public_data: str | None = None
    chat_data: str | None = None
