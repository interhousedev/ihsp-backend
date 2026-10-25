"""Show a screen: answer a message, or edit the message a button was pressed on."""

from app.interfaces.bot.utilities.markup import to_markup
from app.interfaces.bot.utilities.message_split import split_html
from app.shared.contracts.notify import RenderedMessage

import structlog
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

log = structlog.get_logger(__name__)

NOT_MODIFIED = "message is not modified"
QUERY_TOO_OLD = "query is too old"


def is_not_modified(error: TelegramBadRequest) -> bool:
    """Telegram refuses an edit that changes nothing; that is not a failure."""
    return NOT_MODIFIED in error.message


def is_stale_query(error: TelegramBadRequest) -> bool:
    """A callback query older than Telegram's answer window."""
    return QUERY_TOO_OLD in error.message or "query ID is invalid" in error.message


async def answer_callback(callback: CallbackQuery, text: str | None = None) -> None:
    """Answer a callback query, ignoring queries that are too old."""
    try:
        await callback.answer(text=text)
    except TelegramBadRequest as error:
        if not is_stale_query(error):
            raise
        log.info("callback.stale", callback_id=callback.id)


async def _send_parts(
    message: Message, parts: list[str], markup: InlineKeyboardMarkup | None
) -> None:
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        await message.answer(part, reply_markup=markup if last else None)


async def _send_documents(message: Message, rendered: RenderedMessage) -> None:
    for name, data in rendered.documents:
        await message.answer_document(BufferedInputFile(data, filename=name))


async def _edit(message: Message, rendered: RenderedMessage) -> None:
    parts = split_html(rendered.text_html)
    markup = to_markup(rendered.buttons)
    try:
        await message.edit_text(
            parts[0], reply_markup=markup if len(parts) == 1 else None
        )
    except TelegramBadRequest as error:
        if not is_not_modified(error):
            raise
    await _send_parts(message, parts[1:], markup)
    await _send_documents(message, rendered)


async def show(
    request: Message | CallbackQuery,
    rendered: RenderedMessage,
    *,
    toast: str | None = None,
    new_message: bool = False,
) -> None:
    """Show a screen the way the user asked for it.

    A message gets an answer. A button press edits the message the button is on
    (BOT-2), or sends a new message when ``new_message`` is set or the old one is
    no longer accessible (Telegram hides messages older than 48 hours).
    """
    if isinstance(request, Message):
        parts = split_html(rendered.text_html)
        await _send_parts(request, parts, to_markup(rendered.buttons))
        await _send_documents(request, rendered)
        return
    message = request.message
    try:
        if isinstance(message, Message) and not new_message:
            await _edit(message, rendered)
        elif isinstance(message, Message):
            await _send_parts(
                message, split_html(rendered.text_html), to_markup(rendered.buttons)
            )
            await _send_documents(message, rendered)
        else:
            await _send_to_user(request, rendered)
    finally:
        await answer_callback(request, toast)


async def _send_to_user(callback: CallbackQuery, rendered: RenderedMessage) -> None:
    """Fallback for an inaccessible message: write to the user's private chat."""
    bot = callback.bot
    if bot is None:
        return
    parts = split_html(rendered.text_html)
    markup = to_markup(rendered.buttons)
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        await bot.send_message(
            callback.from_user.id, part, reply_markup=markup if last else None
        )
    for name, data in rendered.documents:
        await bot.send_document(
            callback.from_user.id, BufferedInputFile(data, filename=name)
        )
