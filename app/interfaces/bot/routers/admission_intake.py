"""Event intake: a counselor or helper forwards a post, the bot drafts an opportunity.

`/event` (or `/event <text>`) takes a post, a forward, a caption or a link. The
backend researches the links (public pages only) and drafts the entry; the bot asks
for what is missing one question at a time, shows a summary, and on Confirm the
draft goes to the moderation queue. Nothing is published from here.
"""

import datetime as dt
import re
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.reply_edit import show
from app.modules.admission.application.opportunity_intake import (
    IntakeDraft,
    may_submit,
)
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.domain.opportunities import (
    OpportunityDraft,
    OpportunityMaterial,
)
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, MessageOriginChannel

log = structlog.get_logger(__name__)

_TZ = ZoneInfo("Asia/Tashkent")
_KINDS = ("exam", "certification", "course", "event", "recurring")
_FREQS = ("YEARLY", "MONTHLY", "WEEKLY")
_PAGE = 8
_MAX_DATES = 6
_MAX_SUBJECTS = 6
_TITLE_MAX = 200
_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_EDITABLE = ("title", "kind", "dates", "deadline", "recurrence", "subjects")
_KIND_KEYS = {
    "exam": "bot-intake-kind-exam",
    "certification": "bot-intake-kind-certification",
    "course": "bot-intake-kind-course",
    "event": "bot-intake-kind-event",
    "recurring": "bot-intake-kind-recurring",
}
_FREQ_KEYS = {
    "YEARLY": "bot-intake-freq-yearly",
    "MONTHLY": "bot-intake-freq-monthly",
    "WEEKLY": "bot-intake-freq-weekly",
}
_FIELD_KEYS = {
    "title": "bot-intake-field-title",
    "kind": "bot-intake-field-kind",
    "provider": "bot-intake-field-provider",
    "dates": "bot-intake-field-dates",
    "deadline": "bot-intake-field-deadline",
    "recurrence": "bot-intake-field-recurrence",
    "subjects": "bot-intake-field-subjects",
    "url": "bot-intake-field-url",
}
_ASK_DATE_KEYS = {
    "dates": "bot-intake-ask-dates",
    "deadline": "bot-intake-ask-deadline",
}


class IntakeCb(CallbackData, prefix="oi"):
    """Callback data of the intake: an action and a small index.

    `a`: k kind, f frequency, s subject toggle, p page, sd subjects done,
    sk skip, ok confirm, ed edit menu, e edit field, x cancel. `v` is a small
    index, never text or an id.
    """

    a: str
    v: int = 0


class IntakeFlow(StatesGroup):
    """Waiting for the post, then for typed answers."""

    post = State()
    title = State()
    dates = State()
    deadline = State()
    choose = State()  # a button answer (kind, frequency, subjects, summary)


def _btn(text: str, a: str, v: int = 0) -> dict[str, str]:
    return {"text": text, "callback_data": IntakeCb(a=a, v=v).pack()}


def _say(text_html: str, buttons: list[list[dict[str, str]]] | None = None) -> Any:
    return RenderedMessage(text_html=text_html, buttons=buttons or [])


async def _ctx(container: Any, actor: Actor) -> Any | None:
    """The admission context of a permitted submitter, or None."""
    admission = getattr(container, "admission", None)
    if admission is None or getattr(admission, "opportunities", None) is None:
        return None
    legal = getattr(container, "legal", None)
    if legal is not None:
        await legal.require_consent.execute(actor.user_id, "admission")
    ctx = await admission.actor.execute(actor)
    return ctx if may_submit(ctx) else None


def _post_text(message: Message) -> str:
    """The text of a post plus the public link of a forwarded channel post."""
    text = message.text or message.caption or ""
    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel) and origin.chat.username:
        text += f"\nhttps://t.me/{origin.chat.username}/{origin.message_id}"
    return text.strip()


def parse_dates(text: str, today: dt.date) -> list[str]:
    """ISO dates typed as YYYY-MM-DD or DD.MM.YYYY, within three years of today."""
    out: list[str] = []
    for m in _DATE.finditer(text):
        y, mo, d = (m[1], m[2], m[3]) if m[1] else (m[6], m[5], m[4])
        try:
            day = dt.date(int(y), int(mo), int(d))
        except ValueError:
            continue
        if abs((day - today).days) <= 3 * 366 and day.isoformat() not in out:
            out.append(day.isoformat())
    return sorted(out)[:_MAX_DATES]


def _today() -> dt.date:
    return dt.datetime.now(_TZ).date()


def _subjects(taxonomy: list[Any], locale: str) -> list[tuple[str, str]]:
    """(id, `Subfield · Subject`) in the taxonomy order."""

    def name(node: Any) -> str:
        return node.name.get(locale) or node.name.get("en") or ""

    return [
        (str(s.id), f"{name(sub)} · {name(s)}")
        for fld in taxonomy
        for sub in fld.subfields
        for s in sub.subjects
    ]


async def _draft(state: FSMContext) -> IntakeDraft | None:
    data = (await state.get_data()).get("intake")
    return IntakeDraft.from_dict(data) if isinstance(data, dict) else None


async def _keep(state: FSMContext, draft: IntakeDraft) -> None:
    await state.update_data(intake=draft.to_dict())


# - - - Start - - -


async def on_event(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Start the intake; inline text is researched right away."""
    if await _ctx(container, actor) is None:
        await state.clear()
        await show(message, _say(i18n("bot-intake-forbidden")))
        return
    await state.clear()
    if command.args and command.args.strip():
        await _research(message, command.args, state, actor, container, i18n)
        return
    await state.set_state(IntakeFlow.post)
    await show(
        message,
        _say(i18n("bot-intake-ask-post"), [[_btn(i18n("bot-intake-btn-cancel"), "x")]]),
    )


async def on_post(
    message: Message,
    state: FSMContext,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """The post (text, caption or forward)."""
    text = _post_text(message)
    if not text:
        await show(message, _say(i18n("bot-intake-empty")))
        return
    await _research(message, text, state, actor, container, i18n)


async def _research(
    message: Message,
    text: str,
    state: FSMContext,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    ctx = await _ctx(container, actor)
    if ctx is None:
        await state.clear()
        await show(message, _say(i18n("bot-intake-forbidden")))
        return
    await show(message, _say(i18n("bot-intake-working")))
    admission = container.admission
    try:
        taxonomy = await admission.opportunities.taxonomy()
        draft = await admission.opportunity_intake.research(
            ctx, text, locale=i18n.locale, today=_today(), taxonomy=taxonomy
        )
    except AdmissionForbiddenError:
        await state.clear()
        await show(message, _say(i18n("bot-intake-forbidden")))
        return
    except Exception as exc:  # the model or the research failed: say so, keep nothing
        log.warning("opportunity_intake_failed", error=type(exc).__name__)
        await state.clear()
        await show(message, _say(i18n("bot-intake-failed")))
        return
    if "dates" in draft.missing:
        draft.missing.insert(draft.missing.index("dates") + 1, "deadline")
    await _keep(state, draft)
    await _next(message, state, container, i18n, draft)


# - - - Questions - - -


async def _next(
    target: Message | CallbackQuery,
    state: FSMContext,
    container: Any,
    i18n: I18nContext,
    draft: IntakeDraft,
    page: int = 0,
) -> None:
    """Ask the first missing field, or show the summary."""
    if not draft.missing:
        await _summary(target, state, container, i18n, draft)
        return
    field = draft.missing[0]
    cancel = [_btn(i18n("bot-intake-btn-cancel"), "x")]
    skip = [_btn(i18n("bot-intake-btn-skip"), "sk"), *cancel]
    if field == "title":
        await state.set_state(IntakeFlow.title)
        await show(target, _say(i18n("bot-intake-ask-title"), [cancel]))
    elif field == "kind":
        await state.set_state(IntakeFlow.choose)
        rows = [[_btn(i18n(_KIND_KEYS[k]), "k", n)] for n, k in enumerate(_KINDS)]
        await show(target, _say(i18n("bot-intake-ask-kind"), [*rows, cancel]))
    elif field == "recurrence":
        await state.set_state(IntakeFlow.choose)
        rows = [[_btn(i18n(_FREQ_KEYS[f]), "f", n)] for n, f in enumerate(_FREQS)]
        await show(target, _say(i18n("bot-intake-ask-recurrence"), [*rows, skip]))
    elif field in ("dates", "deadline"):
        await state.set_state(
            IntakeFlow.dates if field == "dates" else IntakeFlow.deadline
        )
        current = (
            draft.event_dates if field == "dates" else draft.registration_deadlines
        )
        text = i18n(_ASK_DATE_KEYS[field])
        if current:
            text += "\n" + i18n("bot-intake-current", value=escape(", ".join(current)))
        await show(target, _say(text, [skip]))
    else:
        await _ask_subjects(target, state, container, i18n, draft, page)


async def _ask_subjects(
    target: Message | CallbackQuery,
    state: FSMContext,
    container: Any,
    i18n: I18nContext,
    draft: IntakeDraft,
    page: int,
) -> None:
    await state.set_state(IntakeFlow.choose)
    subjects = _subjects(
        await container.admission.opportunities.taxonomy(), i18n.locale
    )
    if not subjects:  # no taxonomy yet: nothing to pick
        draft.missing.remove("subjects")
        await _keep(state, draft)
        await _next(target, state, container, i18n, draft)
        return
    pages = (len(subjects) + _PAGE - 1) // _PAGE
    page = max(0, min(page, pages - 1))
    rows: list[list[dict[str, str]]] = []
    for n, (sid, label) in enumerate(subjects[page * _PAGE : (page + 1) * _PAGE]):
        mark = "✓ " if sid in draft.subject_ids else ""
        rows.append([_btn(f"{mark}{label}", "s", page * _PAGE + n)])
    nav = []
    if page > 0:
        nav.append(_btn(i18n("bot-intake-btn-prev"), "p", page - 1))
    if page + 1 < pages:
        nav.append(_btn(i18n("bot-intake-btn-next"), "p", page + 1))
    if nav:
        rows.append(nav)
    rows.append(
        [
            _btn(i18n("bot-intake-btn-done"), "sd"),
            _btn(i18n("bot-intake-btn-cancel"), "x"),
        ]
    )
    text = i18n("bot-intake-ask-subjects", limit=_MAX_SUBJECTS)
    await show(target, _say(text, rows))


async def on_title(
    message: Message, state: FSMContext, container: Any, i18n: I18nContext
) -> None:
    """The typed title."""
    draft = await _draft(state)
    text = " ".join((message.text or "").split())
    if draft is None:
        await state.clear()
        await show(message, _say(i18n("bot-intake-expired")))
        return
    if not text or len(text) > _TITLE_MAX:
        await show(message, _say(i18n("bot-intake-bad-title", limit=_TITLE_MAX)))
        return
    draft.title = text
    draft.missing = [f for f in draft.missing if f != "title"]
    await _keep(state, draft)
    await _next(message, state, container, i18n, draft)


async def on_dates(
    message: Message, state: FSMContext, container: Any, i18n: I18nContext
) -> None:
    """Typed event dates or registration deadlines."""
    draft = await _draft(state)
    if draft is None:
        await state.clear()
        await show(message, _say(i18n("bot-intake-expired")))
        return
    days = parse_dates(message.text or "", _today())
    if not days:
        await show(message, _say(i18n("bot-intake-bad-date")))
        return
    field = draft.missing[0] if draft.missing else "dates"
    if field == "deadline":
        draft.registration_deadlines = days
    else:
        draft.event_dates = days
    draft.missing = draft.missing[1:]
    await _keep(state, draft)
    await _next(message, state, container, i18n, draft)


async def on_typed_choice(message: Message, i18n: I18nContext) -> None:
    """Typed text while a button answer is expected: a hint, the state stays."""
    await show(message, _say(i18n("bot-intake-use-buttons")))


async def on_choice(  # noqa: C901 - one dispatch over the flow's buttons
    callback: CallbackQuery,
    callback_data: IntakeCb,
    state: FSMContext,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Every button of the flow."""
    a, v = callback_data.a, callback_data.v
    if a == "x":
        await state.clear()
        await show(callback, _say(i18n("bot-intake-cancelled")))
        return
    draft = await _draft(state)
    if draft is None:
        await callback.answer(i18n("bot-intake-expired"), show_alert=True)
        return
    field = draft.missing[0] if draft.missing else ""
    if a == "k" and field == "kind" and 0 <= v < len(_KINDS):
        draft.kind = _KINDS[v]
        draft.missing = draft.missing[1:]
        if draft.kind == "recurring" and not draft.recurrence:
            draft.missing.insert(0, "recurrence")
    elif a == "f" and field == "recurrence" and 0 <= v < len(_FREQS):
        draft.recurrence = _rule(_FREQS[v], draft)
        draft.missing = draft.missing[1:]
    elif a == "sk" and field in ("dates", "deadline", "recurrence"):
        draft.missing = draft.missing[1:]
    elif a == "s" and field == "subjects":
        subjects = _subjects(
            await container.admission.opportunities.taxonomy(), i18n.locale
        )
        if 0 <= v < len(subjects):
            sid = subjects[v][0]
            if sid in draft.subject_ids:
                draft.subject_ids.remove(sid)
            elif len(draft.subject_ids) < _MAX_SUBJECTS:
                draft.subject_ids.append(sid)
        await _keep(state, draft)
        await _ask_subjects(callback, state, container, i18n, draft, v // _PAGE)
        return
    elif a == "p" and field == "subjects":
        await _ask_subjects(callback, state, container, i18n, draft, v)
        return
    elif a == "sd" and field == "subjects":
        draft.missing = draft.missing[1:]
    elif a == "ed" and not draft.missing:
        rows = [[_btn(i18n(_FIELD_KEYS[f]), "e", n)] for n, f in enumerate(_EDITABLE)]
        await show(callback, _say(i18n("bot-intake-edit-ask"), rows))
        return
    elif a == "e" and not draft.missing and 0 <= v < len(_EDITABLE):
        draft.missing = [_EDITABLE[v]]
    elif a == "ok" and not draft.missing:
        await _submit(callback, state, actor, container, i18n, draft)
        return
    else:
        await callback.answer(i18n("bot-intake-expired"), show_alert=True)
        return
    await _keep(state, draft)
    await _next(callback, state, container, i18n, draft)


def _rule(freq: str, draft: IntakeDraft) -> str:
    """An RRULE of the chosen frequency anchored on the first known date."""
    first = (draft.event_dates or draft.registration_deadlines or [""])[0]
    if not first:
        return f"FREQ={freq};INTERVAL=1"
    day = dt.date.fromisoformat(first)
    if freq == "YEARLY":
        return f"FREQ=YEARLY;INTERVAL=1;BYMONTH={day.month};BYMONTHDAY={day.day}"
    if freq == "MONTHLY":
        return f"FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY={day.day}"
    return "FREQ=WEEKLY;INTERVAL=1"


# - - - Summary and submit - - -


async def _summary(
    target: Message | CallbackQuery,
    state: FSMContext,
    container: Any,
    i18n: I18nContext,
    draft: IntakeDraft,
) -> None:
    await state.set_state(IntakeFlow.choose)
    names = dict(
        _subjects(await container.admission.opportunities.taxonomy(), i18n.locale)
    )
    none = i18n("bot-intake-none")

    def row(key: str, value: str) -> str:
        return f"<b>{i18n(_FIELD_KEYS[key])}:</b> {escape(value) if value else none}"

    lines = [
        f"<b>{i18n('bot-intake-summary-title')}</b>",
        row("title", draft.title),
        row("kind", i18n(_KIND_KEYS.get(draft.kind, "bot-intake-kind-event"))),
        row("provider", draft.provider),
        row("dates", ", ".join(draft.event_dates)),
        row("deadline", ", ".join(draft.registration_deadlines)),
        row("recurrence", draft.recurrence),
        row(
            "subjects",
            ", ".join(names.get(s, "") for s in draft.subject_ids if s in names),
        ),
        row("url", draft.url),
    ]
    if draft.summary:
        lines.append(escape(draft.summary[:600]))
    if draft.materials:
        lines.append(f"<b>{i18n('bot-intake-field-materials')}:</b>")
        lines += [
            f"• {escape(m['title'])}: {escape(m['url'])}" for m in draft.materials
        ]
    if draft.blocked:
        lines.append(i18n("bot-intake-blocked", count=len(draft.blocked)))
    buttons = [
        [_btn(i18n("bot-intake-btn-confirm"), "ok")],
        [
            _btn(i18n("bot-intake-btn-edit"), "ed"),
            _btn(i18n("bot-intake-btn-cancel"), "x"),
        ],
    ]
    await show(target, _say("\n".join(lines), buttons))


async def _submit(
    callback: CallbackQuery,
    state: FSMContext,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
    draft: IntakeDraft,
) -> None:
    ctx = await _ctx(container, actor)
    if ctx is None:
        await state.clear()
        await show(callback, _say(i18n("bot-intake-forbidden")))
        return
    proposal = OpportunityDraft(
        kind=draft.kind,  # type: ignore[arg-type]
        title=draft.title,
        summary=draft.summary or None,
        url=draft.url or None,
        provider=draft.provider or None,
        subject_ids=tuple(UUID(s) for s in draft.subject_ids),
        registration_deadlines=tuple(
            dt.date.fromisoformat(d) for d in draft.registration_deadlines
        ),
        exam_dates=tuple(dt.date.fromisoformat(d) for d in draft.event_dates),
        recurrence=draft.recurrence or None,
        materials=tuple(
            OpportunityMaterial(kind="link", title=m["title"], url=m["url"])
            for m in draft.materials
        ),
        note="Sent through the bot event intake.",
    )
    try:
        await container.admission.opportunities.submit(ctx, proposal)
    except AdmissionForbiddenError:
        await state.clear()
        await show(callback, _say(i18n("bot-intake-forbidden")))
        return
    except RateLimitedError:
        await state.clear()
        await show(callback, _say(i18n("bot-intake-rate-limited")))
        return
    except ValidationFailedError as exc:  # also InvalidProofUrlError
        field = str((exc.params or {}).get("field") or "url")
        await show(
            callback,
            _say(
                i18n("bot-intake-invalid", field=escape(field)),
                [
                    [
                        _btn(i18n("bot-intake-btn-edit"), "ed"),
                        _btn(i18n("bot-intake-btn-cancel"), "x"),
                    ]
                ],
            ),
        )
        return
    await state.clear()
    await show(callback, _say(i18n("bot-intake-submitted")))


def build_router() -> Router:
    """Build the event intake router (before feedback and the assistant)."""
    router = Router(name="admission.intake")
    router.message.register(on_event, Command("event"))
    router.message.register(on_post, IntakeFlow.post)
    router.message.register(on_title, IntakeFlow.title, F.text)
    router.message.register(on_dates, IntakeFlow.dates, F.text)
    router.message.register(on_dates, IntakeFlow.deadline, F.text)
    router.message.register(on_typed_choice, IntakeFlow.choose, ~F.text.startswith("/"))
    router.callback_query.register(on_choice, IntakeCb.filter())
    return router
