"""Slash commands: the catalogue and the per-chat list for a user's roles."""

from collections.abc import Iterable

from app.shared.actor import Role
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat

log = structlog.get_logger(__name__)

# BOT-9: slash commands and the i18n key of their description.
COMMAND_KEYS = {
    "start": "bot-command-start",
    "menu": "bot-command-menu",
    "today": "bot-command-today",
    "marks": "bot-command-marks",
    "homework": "bot-command-homework",
    "lesson": "bot-command-lesson",
    "mail": "bot-command-mail",
    "workoffs": "bot-command-workoffs",
    "settings": "bot-command-settings",
    "new": "bot-command-new",
    "feedback": "bot-command-feedback",
    "help": "bot-command-help",
}


# Commands that only one role uses; every other command is shown to everyone.
STUDENT_ONLY = frozenset({"marks", "homework", "mail"})
TEACHER_ONLY = frozenset({"lesson"})


def command_names_for(roles: Iterable[Role]) -> list[str]:
    """The slash commands a user with these roles can use, in menu order."""
    held = set(roles)
    hidden: set[str] = set()
    if Role.STUDENT not in held:
        hidden |= STUDENT_ONLY
    if Role.TEACHER not in held:
        hidden |= TEACHER_ONLY
    return [name for name in COMMAND_KEYS if name not in hidden]


async def set_role_commands(
    bot: Bot, chat_id: int, user: UserRef, i18n: I18nContext
) -> None:
    """Show this chat only the commands its user's roles can use (best effort)."""
    commands = [
        BotCommand(command=name, description=i18n(COMMAND_KEYS[name]))
        for name in command_names_for(user.roles)
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    except TelegramAPIError as error:
        log.warning("bot.commands_failed", chat_id=chat_id, error=str(error))


async def reset_role_commands(bot: Bot, chat_id: int) -> None:
    """Drop the chat's own command list (after Log out): the default one applies."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
    except TelegramAPIError as error:
        log.warning("bot.commands_reset_failed", chat_id=chat_id, error=str(error))
