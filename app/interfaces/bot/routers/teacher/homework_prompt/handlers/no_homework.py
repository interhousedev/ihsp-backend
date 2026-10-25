"""No homework: close the prompt (BOT-18, UF-BOT-08 alternative 4b)."""

from dataclasses import replace

from app.interfaces.bot.routers.teacher.prompt_flow import load_state
from app.interfaces.bot.screens.lesson_prompt import build_lesson_prompt
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.actor import Actor
from app.shared.contracts.callbacks import HomeworkPromptCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def no_homework(
    callback: CallbackQuery,
    callback_data: HomeworkPromptCb,
    user: UserRef,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Make sure the lesson has no homework and show the closed summary."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    state = await load_state(
        callback, user=user, lesson_id=lesson_id, services=services, i18n=i18n
    )
    if state is None:
        return
    if state.homework_text:
        await services.classwork.clear_homework(lesson_id, actor)
        state = replace(state, homework_text=None)
    closed = build_lesson_prompt(
        state, i18n, now=services.clock.now(), urls=services.urls, mode="closed"
    )
    await show(callback, closed)
