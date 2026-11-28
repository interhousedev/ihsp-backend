"""Maintenance mode for the bot: writes are refused with a notice, reads pass."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.interfaces.bot.assistant.deliver import AiCallCb, AiVizCb
from app.interfaces.bot.callbacks import (
    JournalMarkCb,
    MailComposeCb,
    WorkOffDoneCb,
    WorkOffUndoCb,
)
from app.interfaces.bot.routers.common.assistant.handlers.delete_chat import (
    AiDeleteCb,
)
from app.interfaces.bot.routers.common.feedback.callbacks import FeedbackStepCb
from app.shared.contracts.callbacks import (
    AttActionCb,
    ClubTransferCb,
    ExcuseCb,
    HomeworkDoneCb,
    HomeworkPromptCb,
    MailCb,
    McpScopeCb,
    SettingsCb,
)

from aiogram import BaseMiddleware
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, TelegramObject

# Commands that write: /new and /delete change assistant chats.
WRITE_COMMANDS = frozenset({"new", "delete"})

# Callbacks that always write.
_ALWAYS: tuple[type[CallbackData], ...] = (
    ExcuseCb,
    ClubTransferCb,
    McpScopeCb,
    HomeworkDoneCb,
    WorkOffDoneCb,
    WorkOffUndoCb,
    JournalMarkCb,
    AiCallCb,
    AiVizCb,
    AiDeleteCb,
)

# Callbacks that write for some of their actions: (class, writing actions).
# Security buttons (OtpCancelCb, NotMeCb) stay open: they protect the account.
_BY_ACTION: tuple[tuple[type[CallbackData], frozenset[str]], ...] = (
    (AttActionCb, frozenset({"submit", "submit_none", "all_present"})),
    (HomeworkPromptCb, frozenset({"save", "none"})),
    (MailCb, frozenset({"spam", "unspam"})),
    (MailComposeCb, frozenset({"send"})),
    (FeedbackStepCb, frozenset({"send"})),
)


def _prefix(data: str) -> str:
    return data.split(":", 1)[0]


def is_write_callback(data: str | None) -> bool:
    """True when pressing the button with this callback data mutates state."""
    if not data:
        return False
    prefix = _prefix(data)
    if any(cb.__prefix__ == prefix for cb in _ALWAYS):
        return True
    for cb, actions in _BY_ACTION:
        if cb.__prefix__ == prefix:
            return getattr(cb.unpack(data), "action", None) in actions
    if prefix == SettingsCb.__prefix__:
        setting = SettingsCb.unpack(data)
        reading = setting.key == "open" or (
            setting.key == "logout" and setting.value == "ask"
        )
        return not reading
    return False


def is_write_message(message: Message) -> bool:
    """True for a message that calls the model, feeds an input or writes."""
    text = message.text or ""
    if not text.startswith("/"):
        return True  # assistant questions, files, voice and FSM inputs
    command, _, args = text[1:].partition(" ")
    command = command.split("@", 1)[0].lower()
    return command in WRITE_COMMANDS or (command == "start" and bool(args.strip()))


class MaintenanceMiddleware(BaseMiddleware):
    """Answer writes with the maintenance notice while the platform is read-only."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Refuse a write event during maintenance; pass everything else on."""
        admin = getattr(data["container"], "admin", None)
        gate = getattr(admin, "migration", None)
        if gate is None or not gate.info().active:
            return await handler(event, data)
        text = data["i18n"]("error-maintenance")
        if isinstance(event, CallbackQuery) and is_write_callback(event.data):
            await event.answer(text, show_alert=True)
            return None
        if isinstance(event, Message) and is_write_message(event):
            await event.answer(text)
            return None
        return await handler(event, data)
