"""Handlers of the guest mode: the /start choice, the post tree and the assistant."""

import time
from collections.abc import AsyncIterator
from typing import Any

from app.interfaces.bot.richtext import render_partial, render_telegram
from app.interfaces.bot.routers.auth.login.handlers.show_login import show_login
from app.interfaces.bot.routers.guest.callbacks import PostCb, StartModeCb
from app.interfaces.bot.routers.guest.screens import build_choice, build_post
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.modules.posts.application.guest_assistant import GuestAssistant
from app.modules.posts.domain.bot_mode import BotMode
from app.modules.posts.domain.errors import GuestBusyError, GuestLimitError
from app.modules.posts.domain.post import Viewer
from app.modules.posts.wiring import PostsServices
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

log = structlog.get_logger(__name__)

EDIT_EVERY_SECONDS = 1.5
STREAM_PREVIEW_MAX = 3900


def _posts(container: Any) -> PostsServices:
    posts: PostsServices = container.posts
    return posts


async def start(
    message: Message, container: Any, i18n: I18nContext, locale: str
) -> None:
    """/start of an unlinked account: the choice, or the main menu for a guest."""
    user = message.from_user
    mode = await _posts(container).bot_modes.get(user.id) if user else None
    if mode == BotMode.GUEST:
        await show_menu(message, container, i18n, locale)
        return
    await show(message, build_choice(i18n))


async def choose_mode(
    callback: CallbackQuery,
    callback_data: StartModeCb,
    container: Any,
    state: FSMContext,
    services: BotServices,
    i18n: I18nContext,
    locale: str,
) -> None:
    """Store the choice; a student goes to Log in, a guest to the main menu."""
    mode = BotMode.GUEST if callback_data.mode == "guest" else BotMode.STUDENT
    await _posts(container).bot_modes.choose(callback.from_user.id, mode)
    await answer_callback(callback)
    if mode == BotMode.STUDENT:
        await show_login(callback, state, services, i18n)
        return
    await show_menu(callback, container, i18n, locale)


async def show_menu(
    request: Message | CallbackQuery,
    container: Any,
    i18n: I18nContext,
    locale: str,
    user: UserRef | None = None,
) -> None:
    """The root post (main menu) for the viewer."""
    viewer = Viewer.STUDENT if user is not None else Viewer.GUEST
    screen = await _posts(container).bot_posts.root(viewer)
    await show(request, build_post(screen, locale, i18n, guest=user is None))


async def open_post(
    callback: CallbackQuery,
    callback_data: PostCb,
    container: Any,
    i18n: I18nContext,
    locale: str,
    user: UserRef | None = None,
) -> None:
    """Open a post in place; a hidden or deleted post shows the main menu."""
    await answer_callback(callback)
    post_id = callback_data.post_id()
    viewer = Viewer.STUDENT if user is not None else Viewer.GUEST
    posts = _posts(container).bot_posts
    screen = await posts.open(post_id, viewer) if post_id else None
    if screen is None:
        screen = await posts.root(viewer)
    await show(callback, build_post(screen, locale, i18n, guest=user is None))


async def _edit(bot: Bot, message: Message, text: str) -> None:
    try:
        await bot.edit_message_text(
            text=text, chat_id=message.chat.id, message_id=message.message_id
        )
    except TelegramBadRequest as error:
        log.info("guest.edit_failed", error=error.message)


async def _stream(bot: Bot, reply: Message, deltas: AsyncIterator[str]) -> str:
    """Collect the answer, editing a preview at most every EDIT_EVERY_SECONDS."""
    text = ""
    last_edit = time.monotonic()
    async for delta in deltas:
        text += delta
        if time.monotonic() - last_edit >= EDIT_EVERY_SECONDS:
            preview = render_partial(text[:STREAM_PREVIEW_MAX])
            if preview:
                await _edit(bot, reply, preview[0].text)
            last_edit = time.monotonic()
    return text


async def _admitted(
    message: Message, assistant: GuestAssistant, i18n: I18nContext
) -> bool:
    """Count the question; answer the guest and return False over a limit."""
    if message.from_user is None:
        return False
    try:
        await assistant.check_limits(message.from_user.id)
    except GuestBusyError:
        await message.answer(i18n("bot-guest-busy"))
        return False
    except GuestLimitError:
        await message.answer(i18n("bot-guest-limit"))
        return False
    return True


async def ask_assistant(
    message: Message, bot: Bot, container: Any, i18n: I18nContext, locale: str
) -> None:
    """Answer a guest's free text with the guest assistant, streamed by edits."""
    if message.from_user is None or not message.text:
        return
    assistant = _posts(container).guest_assistant
    if not await _admitted(message, assistant, i18n):
        return
    reply = await message.answer(i18n("bot-guest-thinking"))
    try:
        text = await _stream(
            bot, reply, assistant.stream_answer(message.text, locale=locale)
        )
    except Exception:  # noqa: BLE001  any model failure becomes one apology
        log.exception("guest.assistant_failed")
        await _edit(bot, reply, i18n("bot-guest-error"))
        return
    chunks = render_telegram(text) if text.strip() else []
    if not chunks:
        await _edit(bot, reply, i18n("bot-guest-no-answer"))
        return
    await _edit(bot, reply, chunks[0].text)
    for chunk in chunks[1:]:
        await bot.send_message(message.chat.id, chunk.text)
