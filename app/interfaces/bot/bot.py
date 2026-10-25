"""Bot and dispatcher construction: storage, middlewares and routers."""

from typing import Any

from app.interfaces.bot.middlewares.actor import ActorMiddleware
from app.interfaces.bot.middlewares.error_handler import ErrorMiddleware
from app.interfaces.bot.middlewares.i18n import SUPPORTED_LOCALES, I18nMiddleware
from app.interfaces.bot.middlewares.reset_state import ResetStateMiddleware
from app.interfaces.bot.middlewares.services import ServicesMiddleware
from app.interfaces.bot.routers import build_routers
from app.settings import Settings
from app.shared.i18n.core import I18nCore

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand

FSM_TTL_SECONDS = 3600  # BOT-4: conversation state lives one hour
FSM_KEY_PREFIX = "ihsp:fsm"

# BOT-9: slash commands and the i18n key of their description.
COMMAND_KEYS = {
    "start": "bot-command-start",
    "menu": "bot-command-menu",
    "today": "bot-command-today",
    "marks": "bot-command-marks",
    "homework": "bot-command-homework",
    "mail": "bot-command-mail",
    "workoffs": "bot-command-workoffs",
    "settings": "bot-command-settings",
    "new": "bot-command-new",
    "feedback": "bot-command-feedback",
    "help": "bot-command-help",
}


def build_bot(settings: Settings) -> Bot:
    """Create the Bot: HTML messages, no link previews."""
    return Bot(
        token=settings.telegram.bot_token.get_secret_value(),
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, link_preview_is_disabled=True
        ),
    )


def build_storage(settings: Settings) -> BaseStorage:
    """Redis storage with a one hour TTL; memory in fake mode (no Redis needed)."""
    if settings.telegram.mode == "fake":
        return MemoryStorage()
    return RedisStorage.from_url(
        settings.redis.url,
        key_builder=DefaultKeyBuilder(prefix=FSM_KEY_PREFIX, with_bot_id=True),
        state_ttl=FSM_TTL_SECONDS,
        data_ttl=FSM_TTL_SECONDS,
    )


def build_dispatcher(container: Any, storage: BaseStorage) -> Dispatcher:
    """Create the dispatcher with middlewares and routers.

    Middleware order (outermost first): errors, services, actor, i18n. Errors come
    first so that a failing lookup still produces a user message.
    """
    settings: Settings = container.settings
    dispatcher = Dispatcher(storage=storage, container=container)
    dispatcher.update.outer_middleware(ErrorMiddleware(settings.telegram.admin_chat_id))
    dispatcher.update.outer_middleware(ServicesMiddleware())
    dispatcher.update.outer_middleware(ActorMiddleware())
    dispatcher.update.outer_middleware(I18nMiddleware())
    dispatcher.message.outer_middleware(ResetStateMiddleware())
    dispatcher.callback_query.outer_middleware(ResetStateMiddleware())
    dispatcher.include_routers(*build_routers())
    return dispatcher


def build_commands(i18n_core: I18nCore, locale: str) -> list[BotCommand]:
    """The command list in one language."""
    context = i18n_core.get_context(locale)
    return [
        BotCommand(command=name, description=context(key))
        for name, key in COMMAND_KEYS.items()
    ]


async def set_commands(bot: Bot, i18n_core: I18nCore) -> None:
    """Publish the command list: a default one and one per language."""
    await bot.set_my_commands(build_commands(i18n_core, "en"))
    for locale in SUPPORTED_LOCALES:
        await bot.set_my_commands(
            build_commands(i18n_core, locale), language_code=locale
        )
