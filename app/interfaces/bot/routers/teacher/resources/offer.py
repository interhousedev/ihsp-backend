"""Offer the lessons (or the two roles) once a file or a link has been received."""

from datetime import timedelta
from typing import Any

from app.interfaces.bot.routers.teacher.resources.states import ResourceStates
from app.interfaces.bot.screens.resource_pick import (
    build_resource_pick,
    build_resource_roles,
)
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.clock import local_today
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

LOOK_AHEAD_DAYS = 7
# Telegram lets bots download up to 20 MB; the docs do not say whether MB is 10^6
# or 2^20 bytes, so stay below (docs/reference/telegram.md § 7).
MAX_FILE_BYTES = 20 * 1000 * 1000


async def upcoming_lessons(user: UserRef, services: BotServices) -> list[LessonRef]:
    """Today's and the coming days' lessons of the teacher, soonest first."""
    today = local_today(services.clock)
    end = today + timedelta(days=LOOK_AHEAD_DAYS)
    lessons = await services.schedule.lessons_for_teacher(user.id, today, end)
    now = services.clock.now()
    live = [x for x in lessons if x.status == "scheduled" and x.ends_at > now]
    return sorted(live, key=lambda lesson: lesson.starts_at)


async def offer_lessons(
    message: Message,
    state: FSMContext,
    content: dict[str, Any],
    *,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Store the received content and ask where it goes (BOT-20, BOT-23)."""
    preselected = (await state.get_data()).get("lesson")
    await state.set_state(ResourceStates.choosing)
    await state.set_data({**content, "lesson": preselected})
    lessons = await upcoming_lessons(user, services)
    if preselected:
        chosen = next((x for x in lessons if x.id == b64_to_uuid(preselected)), None)
        if chosen is not None:
            await show(message, build_resource_roles(chosen, i18n))
            return
    if not lessons:
        await state.clear()
    await show(message, build_resource_pick(lessons, i18n))
