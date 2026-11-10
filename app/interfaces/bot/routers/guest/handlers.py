"""Handlers of the guest mode: the /start choice, the post tree and the assistant."""

import time
from collections.abc import AsyncIterator
from typing import Any

from app.interfaces.bot.richtext import render_partial, render_telegram
from app.interfaces.bot.routers.auth.login.handlers.show_login import show_login
from app.interfaces.bot.routers.guest.callbacks import PostCb, StartModeCb
from app.interfaces.bot.routers.guest.screens import build_choice, build_post
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.markup import to_markup, web_app_button
from app.interfaces.bot.utilities.parse_fallback import is_markup_error, plain_fallback
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.interfaces.bot.widgets.deliver import WidgetPlan, plan_widgets, send_widgets
from app.modules.posts.application.guest_assistant import GuestAssistant
from app.modules.posts.domain.bot_mode import BotMode
from app.modules.posts.domain.errors import GuestBusyError, GuestLimitError
from app.modules.posts.domain.post import Viewer
from app.modules.posts.wiring import PostsServices
from app.shared.base_error import BaseError
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.openui.visual import has_valid_blocks

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

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


async def _edit(
    bot: Bot,
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=markup,
        )
    except TelegramBadRequest as error:
        if not is_markup_error(error):
            log.info("guest.edit_failed", error=error.message)
            return
        log.info("guest.markup_fallback")
        try:
            await bot.edit_message_text(
                text=plain_fallback(text),
                chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=markup,
            )
        except TelegramBadRequest as again:
            log.info("guest.edit_failed", error=again.message)


async def guest_voice(message: Message, i18n: I18nContext) -> None:
    """Voice and video are for signed-in users: a guest is asked to type."""
    await message.answer(i18n("bot-guest-voice-unsupported"))


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
    await _deliver(message, bot, reply, container, text, i18n)


async def _deliver(
    message: Message,
    bot: Bot,
    reply: Message,
    container: Any,
    text: str,
    i18n: I18nContext,
) -> None:
    """Send the answer text, its Mini App button and its widgets."""
    assert message.from_user is not None
    plan = _widget_plan(message, container, text) if has_valid_blocks(text) else None
    chunks = render_telegram(plan.text if plan else text) if text.strip() else []
    markup = await _visual_markup(container, message.from_user.id, text, i18n)
    if not chunks and plan is not None:
        await _edit(bot, reply, i18n("bot-ai-visualization"), markup)
    elif not chunks:
        await _edit(bot, reply, i18n("bot-guest-no-answer"))
        return
    else:
        last = len(chunks) - 1
        await _edit(bot, reply, chunks[0].text, markup if last == 0 else None)
        for index, chunk in enumerate(chunks[1:], 1):
            await _send_html(
                bot, message.chat.id, chunk.text, markup if index == last else None
            )
    if plan is not None:
        await send_widgets(bot, message.chat.id, plan)


def _widget_plan(message: Message, container: Any, text: str) -> WidgetPlan | None:
    """Widgets for a private chat when the flag is on and every block has one."""
    settings = getattr(container, "settings", None)
    if not getattr(getattr(settings, "bot", None), "widgets_enabled", False):
        return None
    if message.chat.type != "private":
        return None
    return plan_widgets(text, viz_token=None, visualize_label="")


async def _visual_markup(
    container: Any, telegram_user_id: int, text: str, i18n: I18nContext
) -> InlineKeyboardMarkup | None:
    """The Mini App button of an answer with blocks; None when it cannot be shared."""
    if not has_valid_blocks(text):
        return None
    try:
        url = await container.links.share_guest_answer.execute(
            telegram_user_id=telegram_user_id, text=text
        )
    except BaseError as error:
        log.info("guest.share_skipped", code=error.code)
        return None
    return to_markup([[web_app_button(i18n("bot-ai-visualization"), url)]])


async def _send_html(
    bot: Bot, chat_id: int, html: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    """A further answer message; plain text if Telegram refuses the markup."""
    try:
        await bot.send_message(chat_id, html, reply_markup=markup)
    except TelegramBadRequest as error:
        if not is_markup_error(error):
            raise
        await bot.send_message(chat_id, plain_fallback(html), reply_markup=markup)
