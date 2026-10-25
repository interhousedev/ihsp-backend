"""Marks of the last 7 days and current semester results (UF-BOT-03)."""

from datetime import timedelta

from app.interfaces.bot.screens.marks import build_marks, parse_marks_state
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.clock import local_today
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message

RECENT_DAYS = 7


async def show_marks(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Show recent marks and the semester standing with Open grades."""
    today = local_today(services.clock)
    start = today - timedelta(days=RECENT_DAYS)
    marks = await services.marks.marks(user.id, None, start, today)
    results = await services.marks.results(user.id, None)
    state = parse_marks_state(marks, results)
    await show(request, build_marks(state, i18n, services.urls.grades))
