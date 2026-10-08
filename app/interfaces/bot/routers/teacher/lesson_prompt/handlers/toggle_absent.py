"""Tap a student: toggle absent in the server-side draft (BOT-17)."""

from app.interfaces.bot.routers.teacher.prompt_flow import run_prompt_action
from app.interfaces.bot.services import BotServices
from app.shared.contracts.callbacks import AttToggleCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def toggle_absent(
    callback: CallbackQuery,
    callback_data: AttToggleCb,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Toggle the student at the pressed position and edit the same message."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    await run_prompt_action(
        callback,
        user=user,
        lesson_id=lesson_id,
        services=services,
        i18n=i18n,
        action=lambda: services.classwork.toggle_draft_absent(
            lesson_id, user.id, callback_data.pos
        ),
        mode="edit",
    )
