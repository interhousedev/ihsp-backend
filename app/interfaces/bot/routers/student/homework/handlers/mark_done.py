"""Tick a homework item and show the list again (UF-BOT-03 step 4)."""

from app.interfaces.bot.routers.student.homework.handlers.show_homework import (
    load_upcoming,
)
from app.interfaces.bot.screens.homework import build_homework
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.actor import Actor
from app.shared.clock import local_today
from app.shared.contracts.callbacks import HomeworkDoneCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def mark_done(
    callback: CallbackQuery,
    callback_data: HomeworkDoneCb,
    user: UserRef,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Set the done flag through classwork, then re-read the list."""
    await services.classwork.set_homework_done(
        b64_to_uuid(callback_data.lesson), actor, callback_data.done
    )
    lessons = await load_upcoming(user, services)
    today = local_today(services.clock)
    await show(callback, build_homework(lessons, i18n, services.urls.homework, today))
