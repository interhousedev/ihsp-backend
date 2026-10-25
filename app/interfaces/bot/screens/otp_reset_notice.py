"""Notice that OTP delivery reset was requested, with a Cancel button."""

from datetime import datetime
from uuid import UUID

from app.interfaces.bot.keyboards import otp_cancel
from app.interfaces.bot.utilities.formatting import fmt_datetime
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_otp_reset_notice(
    request_id: UUID, effective_at: datetime, i18n: I18nContext
) -> RenderedMessage:
    """Say when the reset applies and let the user cancel it."""
    return RenderedMessage(
        text_html=i18n("bot-otp-reset", when=fmt_datetime(effective_at)),
        buttons=otp_cancel.get(i18n, request_id),
    )
