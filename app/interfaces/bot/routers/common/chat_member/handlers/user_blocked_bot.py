"""The user blocked the bot (BOT-22)."""

from app.interfaces.bot.services import BotServices

from aiogram.types import ChatMemberUpdated


async def user_blocked_bot(event: ChatMemberUpdated, services: BotServices) -> None:
    """Stop sending to this account until the user writes again."""
    await services.directory.set_telegram_blocked(event.from_user.id, True)
