"""Map exceptions to a user message and an admin report (21ID style)."""

import traceback
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from app.interfaces.bot.middlewares.i18n import resolve_locale
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.reply_edit import is_stale_query
from app.shared.base_error import BaseError
from app.shared.i18n.core import I18nContext

import structlog
from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import TelegramObject, Update, User

log = structlog.get_logger(__name__)

ALERT_LIMIT = 200  # answerCallbackQuery text
REPORT_CHUNK = 3500
TRACE_FRAMES = 6
EVENT_LIMIT = 1500


class ErrorMiddleware(BaseMiddleware):
    """Outermost middleware of the bot: nothing a handler raises gets past it."""

    def __init__(self, admin_chat_id: int | None) -> None:
        """Store the chat that receives reports about unexpected errors."""
        self.admin_chat_id = admin_chat_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Run the handler; on failure tell the user and report to the admin."""
        try:
            return await handler(event, data)
        except Exception as error:  # noqa: BLE001 - the one place that maps errors
            if isinstance(error, TelegramBadRequest) and is_stale_query(error):
                log.info("bot.stale_query")
                return None
            await self._handle(error, event, data)
            return None

    async def _handle(
        self, error: Exception, event: TelegramObject, data: dict[str, Any]
    ) -> None:
        error_id = str(uuid4())
        log.error(
            "bot.error",
            error_id=error_id,
            error_type=type(error).__name__,
            exc_info=error,
        )
        bot: Bot | None = data.get("bot")
        if bot is None:
            return
        if _is_unexpected(error):
            await self._report(bot, error_id, error, event)
        text = _user_text(error, _i18n(data), error_id)
        if text is not None:
            await _tell_user(bot, event, data.get("event_chat"), data, text)

    async def _report(
        self, bot: Bot, error_id: str, error: Exception, event: TelegramObject
    ) -> None:
        if self.admin_chat_id is None:
            return
        # The last frames hold the cause; the aiogram frames above are noise.
        trace = "".join(traceback.format_exception(error, limit=-TRACE_FRAMES))
        summary = event.model_dump_json(exclude_none=True)[:EVENT_LIMIT]
        report = f"error {error_id}\n\n{trace}\n\n{summary}"
        try:
            for start in range(0, len(report), REPORT_CHUNK):
                chunk = escape(report[start : start + REPORT_CHUNK])
                await bot.send_message(self.admin_chat_id, f"<pre>{chunk}</pre>")
        except TelegramAPIError:
            log.exception("bot.admin_report_failed", error_id=error_id)


def _is_unexpected(error: Exception) -> bool:
    """Expected domain errors (4xx) are not reported to the admin."""
    return not isinstance(error, BaseError) or error.status >= 500


def _i18n(data: dict[str, Any]) -> I18nContext:
    found = data.get("i18n")
    if isinstance(found, I18nContext):
        return found
    user: User | None = data.get("event_from_user")
    locale = resolve_locale(data.get("user"), user)
    return data["container"].i18n.get_context(locale)  # type: ignore[no-any-return]


def _user_text(error: Exception, i18n: I18nContext, error_id: str) -> str | None:
    if isinstance(error, BaseError):
        if not error.notify_user:
            return None
        text = i18n.get(error.message_key, **error.params)
    else:
        text = i18n.get("bot-error-generic")
    return f"{text}\n\n{i18n.get('bot-error-id', error_id=error_id)}"


async def _tell_user(
    bot: Bot,
    event: TelegramObject,
    chat: Any,
    data: dict[str, Any],
    text: str,
) -> None:
    try:
        if isinstance(event, Update) and event.callback_query is not None:
            await bot.answer_callback_query(
                event.callback_query.id,
                text=text.replace("\n\n", " ")[:ALERT_LIMIT],
                show_alert=True,
            )
            return
        user: User | None = data.get("event_from_user")
        chat_id = chat.id if chat is not None else (user.id if user else None)
        if chat_id is not None:
            await bot.send_message(chat_id, escape(text))
    except TelegramAPIError:
        log.exception("bot.error_notice_failed")
