"""`widget_query` updates: taps on widget buttons, always answered.

aiogram has no model for the update, so it reaches the dispatcher as an extra field
of `Update` and no router sees it. A middleware on `dispatcher.update` takes it
before the router chain. The query data is untrusted (a widget's code and state are
public): only `viz:<token>` is read, and the token is checked against the store for
this very user before anything happens.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.interfaces.bot.assistant.service import bot_assistant
from app.interfaces.bot.assistant.visual import (
    VisualFailedError,
    VisualStaleError,
    visual_url,
)
from app.interfaces.bot.middlewares.i18n import resolve_locale
from app.interfaces.bot.widgets.methods import AnswerWidgetQuery
from app.shared.actor import Actor
from app.shared.contracts.identity import UserStatus

import structlog
from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    TelegramObject,
    Update,
)
from aiogram.types import User as TelegramUser

log = structlog.get_logger(__name__)

QUERY_FIELDS = ("widget_query", "shared_widget_query")
VISUAL_PREFIX = "viz:"
MAX_DATA_BYTES = 64


def _query_of(update: Update) -> dict[str, Any] | None:
    extra = update.model_extra or {}
    for field in QUERY_FIELDS:
        query = extra.get(field)
        if isinstance(query, dict) and isinstance(query.get("id"), str):
            return query
    return None


def _token_of(query: dict[str, Any]) -> str | None:
    data = query.get("data")
    if not isinstance(data, str) or len(data.encode()) > MAX_DATA_BYTES:
        return None
    if not data.startswith(VISUAL_PREFIX):
        return None
    token = data[len(VISUAL_PREFIX) :]
    return token if token.isalnum() else None


async def _answer(bot: Bot, query_id: str, data: str | None = None) -> None:
    try:
        await bot(AnswerWidgetQuery(widget_query_id=query_id, data=data))
    except TelegramAPIError as error:
        log.info("bot.widget.answer_failed", error=type(error).__name__)


async def handle_query(query: dict[str, Any], data: dict[str, Any]) -> None:
    """Answer one query; a valid `viz:` token also sends the share link."""
    bot: Bot = data["bot"]
    query_id = str(query["id"])
    sender = query.get("from")
    token = _token_of(query)
    assistant = bot_assistant(data["container"])
    if token is None or assistant is None or not isinstance(sender, dict):
        await _answer(bot, query_id, "stale")
        return
    try:
        from_user = TelegramUser.model_validate(sender)
    except ValueError:
        await _answer(bot, query_id, "stale")
        return
    services = data["services"]
    user = (
        None
        if from_user.is_bot
        else await services.directory.user_by_telegram(from_user.id)
    )
    if user is None or user.status != UserStatus.ACTIVE:
        await _answer(bot, query_id, "stale")
        return
    i18n = services.i18n.get_context(resolve_locale(user, from_user))
    actor = Actor(user_id=user.id, roles=user.roles)
    try:
        url = await visual_url(assistant, data["container"], actor, token)
    except VisualStaleError:
        await _answer(bot, query_id, "stale")
        return
    except VisualFailedError:
        await _answer(bot, query_id, "failed")
        await bot.send_message(from_user.id, i18n("bot-ai-visualization-failed"))
        return
    await _answer(bot, query_id, "ok")
    button = InlineKeyboardButton(text=i18n("bot-ai-visualization"), url=url)
    await bot.send_message(
        from_user.id,
        i18n("bot-ai-visualization"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]),
    )


class WidgetQueryMiddleware(BaseMiddleware):
    """Take `widget_query` updates out of the chain; pass everything else on."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Answer the query (always) and stop; other updates continue."""
        query = _query_of(event) if isinstance(event, Update) else None
        if query is None:
            return await handler(event, data)
        try:
            await handle_query(query, data)
        except Exception:  # the query must be answered whatever failed
            log.exception("bot.widget.query_failed")
            await _answer(data["bot"], str(query["id"]), "failed")
        return None
