"""Shared helpers of the mail composition flows."""

import re
from typing import Any

from app.interfaces.bot.keyboards import cancel, mail_skip_note
from app.interfaces.bot.screens.mail_preview import MailDraft
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State

_ADDRESS = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_SEPARATORS = re.compile(r"[,;\s]+")
SUBJECT_MAX_CHARS = 200


def parse_recipients(text: str) -> list[str] | None:
    """Return the distinct addresses in the text, or None if any is malformed."""
    found = [part.lower() for part in _SEPARATORS.split(text.strip()) if part]
    if not found or not all(_ADDRESS.match(part) for part in found):
        return None
    return list(dict.fromkeys(found))


def ask(i18n: I18nContext, key: str, **params: Any) -> RenderedMessage:
    """A question with the Cancel button every input step has."""
    return RenderedMessage(text_html=i18n(key, **params), buttons=cancel.get(i18n))


def ask_note(i18n: I18nContext) -> RenderedMessage:
    """The optional forward note: Skip or Cancel."""
    return RenderedMessage(
        text_html=i18n("bot-mail-ask-note"), buttons=mail_skip_note.get(i18n)
    )


async def load_draft(state: FSMContext) -> MailDraft:
    """Read the draft kept in the FSM."""
    return MailDraft.from_data(await state.get_data())


async def save_draft(state: FSMContext, draft: MailDraft, step: State) -> None:
    """Store the draft and move to the next step."""
    await state.set_state(step)
    await state.set_data(draft.to_data())
