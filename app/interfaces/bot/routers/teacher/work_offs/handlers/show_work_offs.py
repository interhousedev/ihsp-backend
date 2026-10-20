"""The teacher's open work-offs: /workoffs, the menu button and paging (WO-7)."""

from app.interfaces.bot.callbacks import WorkOffPageCb
from app.interfaces.bot.screens.teacher_work_offs import build_teacher_work_offs
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import MenuCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message


async def show_work_offs(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
    callback_data: MenuCb | WorkOffPageCb | None = None,
) -> None:
    """Re-read the open work-offs and show the requested page."""
    items = await services.classwork_queries.teacher_open_work_offs(
        user.id, user.locale
    )
    page = callback_data.page if isinstance(callback_data, WorkOffPageCb) else 0
    await show(request, build_teacher_work_offs(items, i18n, page=page))
