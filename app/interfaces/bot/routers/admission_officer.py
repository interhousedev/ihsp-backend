"""The transcript officer: the /transcripts list, Done, Undo and the pickup place."""

from typing import Any

from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.reply_edit import show
from app.modules.admission.application.transcripts import TranscriptView
from app.modules.admission.domain.documents import PICKUP_LIMIT
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidTransitionError,
    PickupNotSetError,
    UndoExpiredError,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.callbacks import TrCb
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid, uuid_to_b64

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

_LOCALES = ("uz", "ru", "en")
_PAGE = 10


class PickupFlow(StatesGroup):
    """Asking for the pickup place, one language at a time (uz, ru, en)."""

    uz = State()
    ru = State()
    en = State()


def register_filters(router: Router) -> None:
    """Everything here belongs to transcript officers."""
    router.message.filter(HasRole(Role.TRANSCRIPT_OFFICER))
    router.callback_query.filter(HasRole(Role.TRANSCRIPT_OFFICER))


async def _ctx(container: Any, actor: Actor) -> Any:
    return await container.admission.actor.execute(actor)


def _list_screen(
    views: list[TranscriptView], i18n: I18nContext, note: str | None = None
) -> RenderedMessage:
    lines = [f"<b>{i18n('bot-transcripts-title')}</b>"]
    if note:
        lines.append(note)
    open_items = [v for v in views if v.request.status == "requested"][:_PAGE]
    if not open_items:
        lines.append(i18n("bot-transcripts-empty"))
    buttons: list[list[dict[str, str]]] = []
    for v in open_items:
        lines.append(
            i18n(
                "bot-transcripts-item",
                student=escape(v.student_name),
                klass=escape(v.class_name),
                note=escape(v.request.destination_note or "-"),
            )
        )
        buttons.append(
            [
                {
                    "text": i18n("bot-transcripts-btn-done", student=v.student_name),
                    "callback_data": TrCb(a="d", i=uuid_to_b64(v.request.id)).pack(),
                }
            ]
        )
    buttons.append(
        [
            {
                "text": i18n("bot-transcripts-btn-set-pickup"),
                "callback_data": TrCb(a="p").pack(),
            }
        ]
    )
    return RenderedMessage(text_html="\n\n".join(lines), buttons=buttons)


async def show_transcripts(
    request: Message | CallbackQuery,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
    note: str | None = None,
) -> None:
    """Show the open requests, each with a Done button."""
    ctx = await _ctx(container, actor)
    views = await container.admission.transcripts.officer_queue(ctx)
    await show(request, _list_screen(views, i18n, note))


async def on_list(
    callback: CallbackQuery,
    callback_data: TrCb,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Refresh the list."""
    await show_transcripts(callback, actor, container, i18n)


async def _ask_pickup(
    target: Message | CallbackQuery,
    state: FSMContext,
    stage: int,
    i18n: I18nContext,
) -> None:
    flow = (PickupFlow.uz, PickupFlow.ru, PickupFlow.en)[stage]
    await state.set_state(flow)
    text = i18n("bot-transcripts-pickup-ask", locale=_LOCALES[stage].upper())
    await show(target, RenderedMessage(text_html=text, buttons=[]))


async def on_set_pickup(
    callback: CallbackQuery,
    callback_data: TrCb,
    state: FSMContext,
    i18n: I18nContext,
) -> None:
    """Start the pickup place questions."""
    await state.update_data(pickup={})
    await _ask_pickup(callback, state, 0, i18n)


async def on_pickup_text(
    message: Message,
    state: FSMContext,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Take one language of the pickup place, then save after the last one."""
    current = await state.get_state() or ""
    stage = next((i for i, c in enumerate(_LOCALES) if current.endswith(f":{c}")), 0)
    text = (message.text or "").strip()
    if not text or len(text) > PICKUP_LIMIT:
        await show(
            message,
            RenderedMessage(
                text_html=i18n("bot-transcripts-pickup-bad", limit=PICKUP_LIMIT),
                buttons=[],
            ),
        )
        return
    data = await state.get_data()
    pickup = {**data.get("pickup", {}), _LOCALES[stage]: text}
    await state.update_data(pickup=pickup)
    if stage + 1 < len(_LOCALES):
        await _ask_pickup(message, state, stage + 1, i18n)
        return
    await state.clear()
    ctx = await _ctx(container, actor)
    await container.admission.transcripts.set_pickup(ctx, pickup)
    await show_transcripts(
        message, actor, container, i18n, note=i18n("bot-transcripts-pickup-saved")
    )


async def on_done(
    callback: CallbackQuery,
    callback_data: TrCb,
    user: UserRef,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Mark a request ready (the student is told after the undo window)."""
    try:
        request_id = b64_to_uuid(callback_data.i)
    except ValueError:
        await callback.answer(i18n("bot-transcripts-gone"), show_alert=True)
        return
    ctx = await _ctx(container, actor)
    try:
        res = await container.admission.transcripts.done(ctx, request_id)
    except PickupNotSetError:
        await show(
            callback,
            RenderedMessage(
                text_html=i18n("bot-transcripts-pickup-needed"),
                buttons=[
                    [
                        {
                            "text": i18n("bot-transcripts-btn-set-pickup"),
                            "callback_data": TrCb(a="p").pack(),
                        }
                    ]
                ],
            ),
        )
        return
    except (AdmissionNotFoundError, AdmissionForbiddenError):
        await callback.answer(i18n("bot-transcripts-gone"), show_alert=True)
        return
    except (AdmissionConflictError, InvalidTransitionError):
        await callback.answer(i18n("bot-transcripts-already"), show_alert=True)
        return
    if res.already:
        await callback.answer(i18n("bot-transcripts-already"), show_alert=True)
        return
    await show(
        callback,
        RenderedMessage(
            text_html=i18n("bot-transcripts-done"),
            buttons=[
                [
                    {
                        "text": i18n("bot-transcripts-btn-undo"),
                        "callback_data": TrCb(a="u", i=callback_data.i).pack(),
                    }
                ]
            ],
        ),
    )


async def on_undo(
    callback: CallbackQuery,
    callback_data: TrCb,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Take Done back while the student has not been told."""
    try:
        request_id = b64_to_uuid(callback_data.i)
        ctx = await _ctx(container, actor)
        await container.admission.transcripts.undo(ctx, request_id)
    except UndoExpiredError:
        await show(
            callback,
            RenderedMessage(text_html=i18n("bot-transcripts-undo-late"), buttons=[]),
        )
        return
    except (ValueError, AdmissionNotFoundError, AdmissionForbiddenError):
        await callback.answer(i18n("bot-transcripts-gone"), show_alert=True)
        return
    await show_transcripts(
        callback, actor, container, i18n, note=i18n("bot-transcripts-undone")
    )


def build_router() -> Router:
    """Build the transcript officer router."""
    router = Router(name="admission.officer")
    register_filters(router)
    router.message.register(show_transcripts, Command("transcripts"))
    router.message.register(on_pickup_text, PickupFlow.uz)
    router.message.register(on_pickup_text, PickupFlow.ru)
    router.message.register(on_pickup_text, PickupFlow.en)
    cb = router.callback_query
    cb.register(on_done, TrCb.filter(F.a == "d"))
    cb.register(on_undo, TrCb.filter(F.a == "u"))
    cb.register(on_list, TrCb.filter(F.a == "l"))
    cb.register(on_set_pickup, TrCb.filter(F.a == "p"))
    return router
