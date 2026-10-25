"""The user unblocked the bot (BOT-22)."""

from app.interfaces.bot.services import BotServices

from aiogram.types import ChatMemberUpdated


async def user_unblocked_bot(event: ChatMemberUpdated, services: BotServices) -> None:
    """Resume sending to this account."""
    await services.directory.set_telegram_blocked(event.from_user.id, False)
