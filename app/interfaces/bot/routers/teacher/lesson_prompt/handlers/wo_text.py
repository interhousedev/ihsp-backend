"""The teacher sent the extra work-off text: keep it, show the checklist (WO-5)."""

from app.interfaces.bot.routers.teacher.prompt_flow import run_prompt_action
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.work_off_choice import (
    TEXT_MAX_CHARS,
    load_choice,
    store_choice,
)
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import Message


async def receive_work_off_text(
    message: Message,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Store the text with the lesson's choice and answer with the checklist."""
    text = (message.text or "").strip()
    if not text or len(text) > TEXT_MAX_CHARS:
        await message.answer(i18n("bot-work-off-too-long", limit=TEXT_MAX_CHARS))
        return
    lesson = str((await state.get_data())["work_off_lesson"])
    choice = await load_choice(state, services, user.id, lesson)
    await store_choice(state, lesson, template=choice.template, text=text)
    await state.set_state(None)
    lesson_id = b64_to_uuid(lesson)
    await run_prompt_action(
        message,
        user=user,
        lesson_id=lesson_id,
        services=services,
        i18n=i18n,
        action=lambda: services.classwork.prompt_state(lesson_id, user.id),
        mode="edit",
        fsm=state,
    )
