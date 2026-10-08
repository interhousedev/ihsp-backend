"""Today for teachers: lessons with audience and attendance state."""

from app.interfaces.bot.screens.today_teacher import build_today_teacher
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.clock import local_today
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message


async def show_today_teacher(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Show the teacher's lessons of today; finished ones show attendance state."""
    today = local_today(services.clock)
    lessons = await services.schedule.lessons_for_teacher(user.id, today, today)
    missing = await services.classwork_queries.missing_attendance(user.id, today, today)
    rendered = build_today_teacher(
        lessons, {lesson.id for lesson in missing}, today, services.clock.now(), i18n
    )
    await show(request, rendered)
