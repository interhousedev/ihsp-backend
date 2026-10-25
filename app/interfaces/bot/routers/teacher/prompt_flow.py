"""Shared steps of the lesson prompt flows (attendance, homework, topic, resources)."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.interfaces.bot.prompt_state import PromptState, parse_prompt_state
from app.interfaces.bot.screens.lesson_prompt import PromptMode, build_lesson_prompt
from app.interfaces.bot.screens.lesson_prompt_expired import (
    build_prompt_expired,
    build_prompt_reassigned,
    is_window_closed,
)
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.interfaces.bot.work_off_choice import load_choice
from app.shared.base_error import ConflictError, ForbiddenError
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

Action = Callable[[], Awaitable[dict[str, Any]]]


async def show_blocked(
    request: Message | CallbackQuery,
    error: ForbiddenError,
    lesson_id: UUID,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Explain why the prompt can no longer be used (BOT-19, UF-BOT-08)."""
    if is_window_closed(error):
        rendered = build_prompt_expired(lesson_id, i18n, services.urls)
    else:
        rendered = build_prompt_reassigned(i18n)
    await show(request, rendered)


async def load_state(
    request: Message | CallbackQuery,
    *,
    user: UserRef,
    lesson_id: UUID,
    services: BotServices,
    i18n: I18nContext,
) -> PromptState | None:
    """Read the prompt state; None after telling the teacher it is unusable."""
    try:
        state = parse_prompt_state(
            await services.classwork.prompt_state(lesson_id, user.id)
        )
    except ForbiddenError as error:
        await show_blocked(request, error, lesson_id, services, i18n)
        return None
    if state.expired:
        await show(request, build_prompt_expired(lesson_id, i18n, services.urls))
        return None
    return state


async def run_prompt_action(
    request: Message | CallbackQuery,
    *,
    user: UserRef,
    lesson_id: UUID,
    services: BotServices,
    i18n: I18nContext,
    action: Action,
    mode: PromptMode = "auto",
    fsm: FSMContext | None = None,
) -> None:
    """Run a classwork command and edit the prompt with the state it returns.

    A version conflict shows the current list with a note; an expired or
    reassigned lesson shows the matching message instead. With ``fsm`` the
    checklist also shows the teacher's work-off choice (WO-5).
    """
    note: str | None = None
    try:
        raw = await action()
    except ConflictError:
        raw = await services.classwork.prompt_state(lesson_id, user.id)
        note, mode = i18n("bot-prompt-conflict"), "edit"
    except ForbiddenError as error:
        await show_blocked(request, error, lesson_id, services, i18n)
        return
    state = parse_prompt_state(raw)
    if state.expired:
        await show(request, build_prompt_expired(lesson_id, i18n, services.urls))
        return
    work_off = None
    if fsm is not None:
        work_off = await load_choice(fsm, services, user.id, uuid_to_b64(lesson_id))
    rendered = build_lesson_prompt(
        state,
        i18n,
        now=services.clock.now(),
        urls=services.urls,
        mode=mode,
        note=note,
        work_off=work_off,
    )
    await show(request, rendered)
