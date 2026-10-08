"""TelegramSender over one shared aiogram Bot (HTML parse mode)."""

from typing import Any

from app.modules.notify.domain.telegram_errors import (
    TelegramBlocked,
    TelegramRetryAfter,
    TelegramSendError,
    TelegramSendFailed,
)

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.exceptions import TelegramRetryAfter as AiogramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    WebAppInfo,
)

log = structlog.get_logger(__name__)

_GONE_MARKERS = ("chat not found", "user not found", "peer_id_invalid")
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def create_bot(token: str) -> Bot:
    """Create the process-wide bot with HTML as the default parse mode."""
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def _button(spec: dict[str, Any]) -> InlineKeyboardButton:
    """Build one button from {"text", and callback_data | url | web_app_url}."""
    text = spec["text"]
    if "callback_data" in spec:
        return InlineKeyboardButton(text=text, callback_data=spec["callback_data"])
    if "url" in spec:
        return InlineKeyboardButton(text=text, url=spec["url"])
    if "web_app_url" in spec:
        return InlineKeyboardButton(
            text=text, web_app=WebAppInfo(url=spec["web_app_url"])
        )
    raise ValueError(f"button {text!r} has no callback_data, url or web_app_url")


def keyboard(buttons: list[list[dict[str, Any]]] | None) -> InlineKeyboardMarkup | None:
    """Build an inline keyboard from rows of button dicts; None when empty."""
    rows = [[_button(spec) for spec in row] for row in buttons or [] if row]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def map_error(exc: TelegramAPIError) -> TelegramSendError:
    """Translate an aiogram error into the module's own sending errors."""
    if isinstance(exc, AiogramRetryAfter):
        return TelegramRetryAfter(float(exc.retry_after))
    if isinstance(exc, TelegramForbiddenError):
        return TelegramBlocked(exc.message)
    if isinstance(exc, TelegramBadRequest) and any(
        marker in exc.message.lower() for marker in _GONE_MARKERS
    ):
        return TelegramBlocked(exc.message)
    return TelegramSendFailed(exc.message)


class AiogramTelegramSender:
    """Sends messages and documents through the Bot API."""

    def __init__(self, bot: Bot) -> None:
        """Use the process-wide bot."""
        self.bot = bot

    async def send_message(
        self,
        chat_id: int,
        text_html: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> int:
        """Send an HTML message with an optional inline keyboard."""
        try:
            message = await self.bot.send_message(
                chat_id,
                text_html,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard(buttons),
                link_preview_options=_NO_PREVIEW,
            )
        except TelegramAPIError as exc:
            raise map_error(exc) from exc
        return message.message_id

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption_html: str | None = None,
    ) -> int:
        """Send a file with an optional HTML caption."""
        try:
            message = await self.bot.send_document(
                chat_id,
                BufferedInputFile(data, filename=filename),
                caption=caption_html,
                parse_mode=ParseMode.HTML,
            )
        except TelegramAPIError as exc:
            raise map_error(exc) from exc
        return message.message_id

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Delete a message; one that is already gone or too old is only logged."""
        try:
            await self.bot.delete_message(chat_id, message_id)
        except TelegramAPIError as exc:
            log.warning(
                "telegram_delete_failed",
                chat_id=chat_id,
                message_id=message_id,
                reason=exc.message,
            )

    async def close(self) -> None:
        """Close the bot's HTTP session."""
        await self.bot.session.close()
