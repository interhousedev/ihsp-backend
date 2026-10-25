"""Buttons that are only labels do nothing."""

from app.interfaces.bot.utilities.reply_edit import answer_callback

from aiogram.types import CallbackQuery


async def none(callback: CallbackQuery) -> None:
    """Answer the callback so the button stops spinning."""
    await answer_callback(callback)
