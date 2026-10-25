"""Cancel a pending OTP reset from the notice in Telegram (identity use case)."""

from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import OtpCancelCb
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def cancel_otp_reset(
    callback: CallbackQuery,
    callback_data: OtpCancelCb,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Call identity's ``cancel_otp_reset`` and confirm; the request id is the proof."""
    await services.cancel_otp_reset.execute(b64_to_uuid(callback_data.request))
    await show(callback, RenderedMessage(text_html=i18n("bot-otp-cancelled")))
