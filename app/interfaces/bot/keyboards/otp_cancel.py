"""Keyboard under the OTP reset notice: cancel the reset (UF-ID-04 bot side)."""

from uuid import UUID

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import OtpCancelCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64


def get(i18n: I18nContext, request_id: UUID) -> Rows:
    """Return the Cancel reset row."""
    return [
        [
            cb_button(
                i18n("bot-btn-otp-cancel"), OtpCancelCb(request=uuid_to_b64(request_id))
            )
        ]
    ]
