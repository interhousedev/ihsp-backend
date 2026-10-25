"""FSM states of the feedback flow, in the order the user passes them."""

from aiogram.fsm.state import State, StatesGroup


class FeedbackStates(StatesGroup):
    """Where the user is in the feedback flow."""

    kind = State()
    area = State()
    title = State()
    description = State()
    attachments = State()
    confirm = State()
