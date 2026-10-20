"""One tap marks a work-off done and offers Undo (WO-7)."""

from app.interfaces.bot.callbacks import WorkOffDoneCb
from app.interfaces.bot.screens.teacher_work_offs import build_teacher_work_offs
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.actor import Actor
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def mark_done(
    callback: CallbackQuery,
    callback_data: WorkOffDoneCb,
    user: UserRef,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Set the status to done, then re-render the list with Undo for this one."""
    work_off_id = b64_to_uuid(callback_data.item)
    before = await services.classwork_queries.teacher_open_work_offs(
        user.id, user.locale
    )
    name = next(
        (i["student_name"] for i in before if str(i["id"]) == str(work_off_id)), None
    )
    await services.classwork.set_work_off_status(work_off_id, actor, "done")
    items = await services.classwork_queries.teacher_open_work_offs(
        user.id, user.locale
    )
    note = None if name is None else i18n("bot-workoffs-marked-done", student=name)
    rendered = build_teacher_work_offs(
        items, i18n, page=callback_data.page, undo=callback_data.item, note=note
    )
    await show(callback, rendered)
