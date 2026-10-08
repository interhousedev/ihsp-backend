"""Submit exactly the absent list the teacher saw (BOT-17, UF-BOT-08 step 3)."""

from typing import Any
from uuid import UUID

from app.interfaces.bot.prompt_state import parse_prompt_state
from app.interfaces.bot.routers.teacher.prompt_flow import run_prompt_action
from app.interfaces.bot.services import BotServices
from app.shared.actor import Actor
from app.shared.contracts.callbacks import AttActionCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def _submit(
    services: BotServices, actor: Actor, lesson_id: UUID, *, from_draft: bool
) -> dict[str, Any]:
    """Read the attendance version first; an expired prompt submits nothing."""
    raw = await services.classwork.prompt_state(lesson_id, actor.user_id)
    state = parse_prompt_state(raw)
    if state.expired:
        return raw
    return await services.classwork.submit_attendance(
        lesson_id,
        actor,
        absent=None if from_draft else [],
        from_draft=from_draft,
        base_version=state.attendance_version,
        source="bot",
    )


async def submit_attendance(
    callback: CallbackQuery,
    callback_data: AttActionCb,
    user: UserRef,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Submit the draft (``submit``) or an empty absent list (``all_present``)."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    from_draft = callback_data.action == "submit"
    await run_prompt_action(
        callback,
        user=user,
        lesson_id=lesson_id,
        services=services,
        i18n=i18n,
        action=lambda: _submit(services, actor, lesson_id, from_draft=from_draft),
    )
