"""Leave a half-finished input when the user starts something else."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.shared.contracts.callbacks import MenuCb

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject


def starts_new_task(event: TelegramObject) -> bool:
    """A slash command or a main-menu button abandons the current input."""
    if isinstance(event, Message):
        return bool(event.text and event.text.startswith("/"))
    if isinstance(event, CallbackQuery):
        prefix = MenuCb.__prefix__ + MenuCb.__separator__
        return bool(event.data and event.data.startswith(prefix))
    return False


class ResetStateMiddleware(BaseMiddleware):
    """Clear the FSM state before commands and menu buttons are handled."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Clear the state when the event starts a new task, then continue."""
        state: FSMContext | None = data.get("state")
        if state is not None and starts_new_task(event):
            await state.clear()
        return await handler(event, data)
