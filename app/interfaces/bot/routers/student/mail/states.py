"""FSM states of composing, replying and forwarding an email (MAIL-4)."""

from aiogram.fsm.state import State, StatesGroup


class MailStates(StatesGroup):
    """Where the student is in a mail composition flow."""

    new_to = State()
    new_subject = State()
    new_body = State()
    reply_body = State()
    forward_to = State()
    forward_note = State()
    preview = State()
