"""Submit exactly the absent list the teacher saw (BOT-17, UF-BOT-08 step 3)."""

from typing import Any
from uuid import UUID

from app.interfaces.bot.prompt_state import parse_prompt_state
from app.interfaces.bot.routers.teacher.prompt_flow import run_prompt_action
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.work_off_choice import forget_choice, load_choice
from app.shared.actor import Actor
from app.shared.contracts.callbacks import AttActionCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def _submit(
    services: BotServices,
    actor: Actor,
    lesson: str,
    fsm: FSMContext,
    *,
    from_draft: bool,
    with_work_off: bool,
) -> dict[str, Any]:
    """Read the attendance version first; an expired prompt submits nothing.

    Absent students get the chosen work-off as a common one (WO-5); without a
    choice, or when the teacher asked for none, nothing is attached.
    """
    lesson_id: UUID = b64_to_uuid(lesson)
    raw = await services.classwork.prompt_state(lesson_id, actor.user_id)
    state = parse_prompt_state(raw)
    if state.expired:
        return raw
    choice = await load_choice(fsm, services, actor.user_id, lesson)
    common = with_work_off and from_draft and choice.chosen and state.absent_count > 0
    saved = await services.classwork.submit_attendance(
        lesson_id,
        actor,
        absent=None if from_draft else [],
        from_draft=from_draft,
        base_version=state.attendance_version,
        source="bot",
        work_off_mode="common" if common else "none",
        common_work_off=choice.payload() if common else None,
    )
    await forget_choice(fsm, lesson)
    return saved


async def submit_attendance(
    callback: CallbackQuery,
    callback_data: AttActionCb,
    state: FSMContext,
    user: UserRef,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Submit the draft (``submit``, ``submit_none``) or all present."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    action = callback_data.action
    await run_prompt_action(
        callback,
        user=user,
        lesson_id=lesson_id,
        services=services,
        i18n=i18n,
        action=lambda: _submit(
            services,
            actor,
            callback_data.lesson,
            state,
            from_draft=action != "all_present",
            with_work_off=action == "submit",
        ),
        fsm=state,
    )
