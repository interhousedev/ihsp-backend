"""Today for students: lessons with times and rooms."""

from app.interfaces.bot.screens.today_student import build_today_student
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.clock import local_today
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message


async def show_today_student(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Show the student's lessons of today."""
    today = local_today(services.clock)
    lessons = await services.schedule.lessons_for_student(user.id, today, today)
    await show(request, build_today_student(lessons, today, i18n))
