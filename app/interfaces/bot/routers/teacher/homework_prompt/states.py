"""FSM states of the homework and topic inputs (BOT-17, BOT-18)."""

from aiogram.fsm.state import State, StatesGroup


class HomeworkStates(StatesGroup):
    """The teacher is typing homework or a topic for one lesson."""

    waiting_text = State()
    confirm = State()
    waiting_topic = State()
