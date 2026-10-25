"""Lesson journal: temporary marks from the lesson prompt (TMP-1)."""

from collections.abc import Awaitable
from typing import TypeVar
from uuid import UUID

from app.interfaces.bot.callbacks import JournalCb, JournalMarkCb, JournalStudentCb
from app.interfaces.bot.keyboards.lesson_journal import REMOVE_VALUE
from app.interfaces.bot.prompt_state import PromptState, RosterItem, parse_prompt_state
from app.interfaces.bot.routers.teacher.prompt_flow import (
    run_prompt_action,
    show_blocked,
)
from app.interfaces.bot.screens.lesson_journal import (
    build_journal,
    build_journal_student,
)
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.actor import Actor
from app.shared.base_error import BaseError, ForbiddenError
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

T = TypeVar("T")


class _Failed(Exception):
    """The teacher has already been told why the call failed."""


async def _guard(callback: CallbackQuery, i18n: I18nContext, call: Awaitable[T]) -> T:
    """Await the use case; an expected domain error becomes a localized alert."""
    try:
        return await call
    except BaseError as error:
        if error.status >= 500:
            raise
        await callback.answer(i18n(error.message_key, **error.params), show_alert=True)
        raise _Failed from error


async def _marks(
    services: BotServices, lesson_id: UUID, actor: Actor, user: UserRef
) -> dict[UUID, int]:
    views = await services.temporary_marks.list.execute(
        lesson_id, actor, locale=user.locale
    )
    return {view.mark.student_id: view.mark.value for view in views}


async def _journal_state(
    callback: CallbackQuery,
    *,
    user: UserRef,
    lesson_id: UUID,
    services: BotServices,
    i18n: I18nContext,
) -> PromptState | None:
    """The roster and names of the lesson for the journal.

    Unlike the attendance prompt, the journal stays open after the lesson's day: the
    temporary marks are kept until they are in EMIS. Only a refusal is shown.
    """
    try:
        raw = await services.classwork.prompt_state(lesson_id, user.id)
    except ForbiddenError as error:
        await show_blocked(callback, error, lesson_id, services, i18n)
        return None
    return parse_prompt_state(raw)


def _student(state: PromptState, position: int) -> RosterItem | None:
    return next((item for item in state.roster if item.position == position), None)


async def _show_list(
    callback: CallbackQuery,
    *,
    lesson_id: UUID,
    actor: Actor,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
    toast: str | None = None,
) -> None:
    state = await _journal_state(
        callback, user=user, lesson_id=lesson_id, services=services, i18n=i18n
    )
    if state is None:
        return
    try:
        marks = await _guard(callback, i18n, _marks(services, lesson_id, actor, user))
    except _Failed:
        return
    await show(callback, build_journal(state, marks, i18n), toast=toast)


async def open_journal(
    callback: CallbackQuery,
    callback_data: JournalCb,
    actor: Actor,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Edit the prompt into the list of students with their marks."""
    await _show_list(
        callback,
        lesson_id=b64_to_uuid(callback_data.lesson),
        actor=actor,
        user=user,
        services=services,
        i18n=i18n,
    )


async def close_journal(
    callback: CallbackQuery,
    callback_data: JournalCb,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Back: show the lesson prompt again."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    await run_prompt_action(
        callback,
        user=user,
        lesson_id=lesson_id,
        services=services,
        i18n=i18n,
        action=lambda: services.classwork.prompt_state(lesson_id, user.id),
        fsm=state,
    )


async def open_student(
    callback: CallbackQuery,
    callback_data: JournalStudentCb,
    actor: Actor,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Show the mark buttons of the pressed student."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    state = await _journal_state(
        callback, user=user, lesson_id=lesson_id, services=services, i18n=i18n
    )
    if state is None:
        return
    item = _student(state, callback_data.pos)
    if item is None:
        await _show_list(
            callback,
            lesson_id=lesson_id,
            actor=actor,
            user=user,
            services=services,
            i18n=i18n,
            toast=i18n("bot-journal-roster-changed"),
        )
        return
    try:
        marks = await _guard(callback, i18n, _marks(services, lesson_id, actor, user))
    except _Failed:
        return
    rendered = build_journal_student(state, item, marks.get(item.user_id), i18n)
    await show(callback, rendered)


async def set_mark(
    callback: CallbackQuery,
    callback_data: JournalMarkCb,
    actor: Actor,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Save or remove the mark, then return to the list."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    state = await _journal_state(
        callback, user=user, lesson_id=lesson_id, services=services, i18n=i18n
    )
    if state is None:
        return
    item = _student(state, callback_data.pos)
    toast = i18n("bot-journal-roster-changed")
    if item is not None:
        cases = services.temporary_marks
        try:
            if callback_data.value == REMOVE_VALUE:
                await _guard(
                    callback,
                    i18n,
                    cases.delete.execute(lesson_id, item.user_id, actor),
                )
                toast = i18n("bot-journal-removed")
            else:
                await _guard(
                    callback,
                    i18n,
                    cases.set.execute(
                        lesson_id,
                        item.user_id,
                        actor,
                        value=callback_data.value,
                        locale=user.locale,
                    ),
                )
                toast = i18n("bot-journal-saved")
        except _Failed:
            return
    await _show_list(
        callback,
        lesson_id=lesson_id,
        actor=actor,
        user=user,
        services=services,
        i18n=i18n,
        toast=toast,
    )
