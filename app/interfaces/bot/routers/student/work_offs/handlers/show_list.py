"""The student's open work-offs: /workoffs and the menu button (WO-5)."""

from app.interfaces.bot.screens.student_work_offs import build_student_work_offs
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message


async def show_student_work_offs(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Re-read the open work-offs and show them."""
    items = await services.classwork_queries.my_work_offs(user.id, user.locale)
    await show(request, build_student_work_offs(items, i18n))
