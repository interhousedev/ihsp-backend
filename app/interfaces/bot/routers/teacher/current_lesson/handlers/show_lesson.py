"""The teacher's current or next lesson (UF-BOT-03 step 5)."""

from datetime import timedelta

from app.interfaces.bot.screens.current_lesson import build_current_lesson, pick_lesson
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.clock import local_today
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message

LOOK_AHEAD_DAYS = 7


async def show_current_lesson(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Show the running lesson, or the next one within a week."""
    today = local_today(services.clock)
    end = today + timedelta(days=LOOK_AHEAD_DAYS)
    lessons = await services.schedule.lessons_for_teacher(user.id, today, end)
    now = services.clock.now()
    rendered = build_current_lesson(pick_lesson(lessons, now), now, i18n, services.urls)
    await show(request, rendered)
