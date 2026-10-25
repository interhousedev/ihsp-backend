"""Choice of the TelegramSender by `TELEGRAM__MODE`."""

from collections.abc import Awaitable, Callable

from app.modules.notify.infrastructure.fake_sender import FakeTelegramSender
from app.modules.notify.infrastructure.telegram_sender import (
    AiogramTelegramSender,
    create_bot,
)
from app.settings import Settings
from app.shared.contracts.notify import TelegramSender

from redis.asyncio import Redis

Closer = Callable[[], Awaitable[None]]


def make_telegram_sender(
    settings: Settings, redis: Redis
) -> tuple[TelegramSender, Closer | None]:
    """Return the sender and, for the real one, the coroutine that closes its bot.

    `fake` never touches the network: messages go to the Redis list
    `fake-telegram:outbox`. `polling` and `webhook` send through the Bot API.
    """
    if settings.telegram.mode == "fake":
        return FakeTelegramSender(redis), None
    sender = AiogramTelegramSender(
        create_bot(settings.telegram.bot_token.get_secret_value())
    )
    return sender, sender.close
