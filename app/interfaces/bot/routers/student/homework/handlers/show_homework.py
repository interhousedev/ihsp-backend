"""The Upcoming homework list (UF-BOT-03)."""

from datetime import timedelta

from app.interfaces.bot.screens.homework import build_homework
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.clock import local_today
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message

# Matches the web list, which looks 90 days back for open homework.
OVERDUE_LOOKBACK_DAYS = 90


async def load_upcoming(user: UserRef, services: BotServices) -> list[LessonRef]:
    """Return the lessons with homework the student has not done yet.

    Items past their due date are included, so nothing the teacher set drops off.
    """
    since = local_today(services.clock) - timedelta(days=OVERDUE_LOOKBACK_DAYS)
    items = await services.classwork_queries.homework(user.id, since, None, False)
    return [item["lesson"] for item in items]


async def show_homework(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Show the homework still to do with a Done button per item."""
    lessons = await load_upcoming(user, services)
    today = local_today(services.clock)
    await show(request, build_homework(lessons, i18n, services.urls.homework, today))
