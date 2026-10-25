"""FSM states of adding a resource from Telegram (BOT-20)."""

from aiogram.fsm.state import State, StatesGroup


class ResourceStates(StatesGroup):
    """The teacher is adding a file or a link to a lesson."""

    waiting_content = State()  # started from Current lesson: send a file or a link
    choosing = State()  # content received: pick the lesson / Material or Attachment
