"""Guest mode in any chat (Bot API 10.0): one public answer per @mention.

Only the public guest assistant answers, even for a signed-in user: the answer is
shown in a chat that may have strangers in it, so no personal data is ever used.
"""

import re
import uuid
from typing import Any
from urllib.parse import urlsplit

from app.interfaces.bot.middlewares.i18n import resolve_locale
from app.interfaces.bot.richtext import render_telegram
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.parse_fallback import is_markup_error, plain_fallback
from app.modules.posts.application.guest_assistant import MAX_QUESTION
from app.modules.posts.domain.errors import GuestBusyError, GuestLimitError
from app.shared.ai.injection import is_rule_attack, neutralize_text
from app.shared.openui.degrade import degrade_blocks_last

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
    Message,
    User,
)

log = structlog.get_logger(__name__)

MAX_REPLY = 4096
QUOTE_MAX = 500
TITLE_MAX = 64
_MD_LINK = re.compile(r"\[([^\]\n]*)\]\(\s*([^()\s]+)[^()]*\)")


def strip_mention(text: str, username: str | None) -> str:
    """Remove the bot's @mention from the text."""
    if username:
        text = re.sub(rf"@{re.escape(username)}\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def build_inputs(message: Message, username: str | None) -> tuple[str, str | None]:
    """The caller's own question and the quote (data) that goes beside it.

    The language and the rule check see the own text only. A quote that attacks the
    rules is dropped; without own text the (neutralized) quote is the question.
    """
    own = strip_mention(message.text or message.caption or "", username)[:MAX_QUESTION]
    quoted = message.reply_to_message
    raw = " ".join(((quoted.text or quoted.caption or "") if quoted else "").split())
    if not raw:
        return own, None
    if not own:
        return neutralize_text(raw)[:QUOTE_MAX], None
    return own, (None if is_rule_attack(raw) else raw[:QUOTE_MAX])


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def keep_known_links(text: str, seen: set[str], hosts: set[str]) -> str:
    """Markdown links whose URL the search returned (or on a public host) stay."""

    def check(match: re.Match[str]) -> str:
        url = match.group(2)
        if url in seen or _host(url) in hosts:
            return match.group(0)
        return match.group(1)

    return _MD_LINK.sub(check, text)


def render_reply(text: str) -> str:
    """The answer as Telegram HTML within one message; blocks degrade to Markdown."""
    chunks = render_telegram(degrade_blocks_last(text)) if text.strip() else []
    html = ""
    for chunk in chunks:
        joined = f"{html}\n\n{chunk.text}" if html else chunk.text
        if len(joined) > MAX_REPLY:
            break
        html = joined
    return html


async def _reply(bot: Bot, query_id: str, html: str, title: str) -> None:
    try:
        await _send(bot, query_id, html, title)
    except TelegramBadRequest as error:
        if not is_markup_error(error):
            raise
        log.info("guest_chat.markup_fallback")
        await _send(bot, query_id, plain_fallback(html), title)


async def _send(bot: Bot, query_id: str, html: str, title: str) -> None:
    await bot.answer_guest_query(
        guest_query_id=query_id,
        result=InlineQueryResultArticle(
            id=uuid.uuid4().hex,
            title=title[:TITLE_MAX],
            input_message_content=InputTextMessageContent(
                message_text=html,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            ),
        ),
    )


async def _admitted(
    assistant: Any, bot: Bot, query_id: str, message: Message, caller_id: int, i18n: Any
) -> bool:
    """Count the question; over a limit send the notice once a minute and refuse."""
    try:
        await assistant.check_chat_limits(caller_id, message.chat.id)
    except (GuestBusyError, GuestLimitError) as error:
        if await assistant.first_notice(caller_id):
            key = (
                "bot-guest-busy"
                if isinstance(error, GuestBusyError)
                else ("bot-guest-limit")
            )
            await _reply(bot, query_id, escape(i18n(key)), "…")
        return False
    return True


def _public_hosts(container: Any) -> set[str]:
    settings = getattr(container, "settings", None)
    urls = (
        getattr(getattr(settings, "openrouter", None), "app_url", None),
        getattr(getattr(settings, "library", None), "public_base_url", None),
    )
    return {_host(url) for url in urls if isinstance(url, str) and url}


def _in_maintenance(container: Any) -> bool:
    gate = getattr(getattr(container, "admin", None), "migration", None)
    return gate is not None and bool(gate.info().active)


async def _answer(
    message: Message, bot: Bot, query_id: str, caller: User, container: Any, i18n: Any
) -> None:
    if _in_maintenance(container):
        await _reply(bot, query_id, escape(i18n("error-maintenance")), "…")
        return
    locale = resolve_locale(None, caller)
    assistant = container.posts.guest_assistant
    question, context = build_inputs(message, (await bot.me()).username)
    if not await _admitted(assistant, bot, query_id, message, caller.id, i18n):
        return
    if not question:
        await _reply(bot, query_id, escape(i18n("bot-guest-chat-help")), "?")
        return
    seen: set[str] = set()
    text = "".join(
        [
            delta
            async for delta in assistant.stream_answer(
                question, locale=locale, context=context, seen_urls=seen
            )
        ]
    )
    text = keep_known_links(degrade_blocks_last(text), seen, _public_hosts(container))
    html = render_reply(text) or escape(i18n("bot-guest-no-answer"))
    await _reply(bot, query_id, html, question)


async def answer_guest_chat(
    message: Message, bot: Bot, container: Any, services: BotServices
) -> None:
    """Answer one guest query: limits by the caller, one model call, one reply."""
    query_id = message.guest_query_id
    caller: User | None = message.from_user or message.guest_bot_caller_user
    if not query_id or caller is None or caller.is_bot or message.sender_chat:
        return
    i18n = services.i18n.get_context(resolve_locale(None, caller))
    try:
        await _answer(message, bot, query_id, caller, container, i18n)
    except (
        Exception
    ) as error:  # noqa: BLE001  never crash the dispatcher on a guest query
        log.error(
            "guest_chat.failed", error_type=type(error).__name__, caller_id=caller.id
        )
        try:
            await _reply(bot, query_id, escape(i18n("bot-guest-error")), "!")
        except Exception as reply_error:  # noqa: BLE001  the query may have expired
            log.warning(
                "guest_chat.error_reply_failed",
                error_type=type(reply_error).__name__,
                caller_id=caller.id,
            )
