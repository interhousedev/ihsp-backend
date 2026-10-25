"""Undo the last tap: the work-off goes back to assigned (WO-7)."""

from app.interfaces.bot.callbacks import WorkOffUndoCb
from app.interfaces.bot.screens.teacher_work_offs import build_teacher_work_offs
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.actor import Actor
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def undo_done(
    callback: CallbackQuery,
    callback_data: WorkOffUndoCb,
    user: UserRef,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Set the status back to assigned and re-render the list."""
    await services.classwork.set_work_off_status(
        b64_to_uuid(callback_data.item), actor, "assigned"
    )
    items = await services.classwork_queries.teacher_open_work_offs(
        user.id, user.locale
    )
    note = i18n("bot-workoffs-reopened")
    await show(
        callback,
        build_teacher_work_offs(items, i18n, page=callback_data.page, note=note),
    )
