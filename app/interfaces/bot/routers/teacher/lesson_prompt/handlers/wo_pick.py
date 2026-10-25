"""A template (or None) was picked: remember it and show the checklist (WO-5)."""

from app.interfaces.bot.callbacks import WorkOffPickCb
from app.interfaces.bot.routers.teacher.prompt_flow import run_prompt_action
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.work_off_choice import load_choice, store_choice
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def pick_work_off(
    callback: CallbackQuery,
    callback_data: WorkOffPickCb,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Position 0 clears the work-off; others pick the template at pos - 1."""
    lesson = callback_data.lesson
    choice = await load_choice(state, services, user.id, lesson)
    index = callback_data.pos - 1
    if 0 <= index < len(choice.templates):
        await store_choice(
            state, lesson, template=choice.templates[index], text=choice.text
        )
    else:
        await store_choice(state, lesson, template=None, text=None)
    lesson_id = b64_to_uuid(lesson)
    await run_prompt_action(
        callback,
        user=user,
        lesson_id=lesson_id,
        services=services,
        i18n=i18n,
        action=lambda: services.classwork.prompt_state(lesson_id, user.id),
        mode="edit",
        fsm=state,
    )
