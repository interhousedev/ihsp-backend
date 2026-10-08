"""Callback data used only inside the bot (not shared with notification renderers)."""

from aiogram.filters.callback_data import CallbackData


class MailComposeCb(CallbackData, prefix="mc"):
    """Mail composition step: new, send, edit or skip (the optional forward note)."""

    action: str
