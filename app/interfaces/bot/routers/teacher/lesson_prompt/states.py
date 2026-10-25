"""FSM state of typing the extra work-off text (WO-5)."""

from aiogram.fsm.state import State, StatesGroup


class WorkOffStates(StatesGroup):
    """The teacher is typing a work-off text for one lesson."""

    waiting_text = State()
