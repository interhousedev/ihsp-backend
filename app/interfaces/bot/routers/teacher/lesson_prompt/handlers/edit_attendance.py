"""Show the attendance checklist again: Edit attendance, or from Current lesson."""

from app.interfaces.bot.routers.teacher.prompt_flow import run_prompt_action
from app.interfaces.bot.services import BotServices
from app.shared.contracts.callbacks import AttActionCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def edit_attendance(
    callback: CallbackQuery,
    callback_data: AttActionCb,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Re-read the state and render the checklist, even if it was submitted."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    await run_prompt_action(
        callback,
        user=user,
        lesson_id=lesson_id,
        services=services,
        i18n=i18n,
        action=lambda: services.classwork.prompt_state(lesson_id, user.id),
        mode="edit",
    )
