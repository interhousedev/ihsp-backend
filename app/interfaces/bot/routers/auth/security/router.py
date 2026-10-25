"""Router for security buttons; they work even if the account got unlinked."""

from app.interfaces.bot.routers.auth.security.handlers.cancel_otp_reset import (
    cancel_otp_reset,
)
from app.interfaces.bot.routers.auth.security.handlers.not_me import not_me
from app.shared.contracts.callbacks import NotMeCb, OtpCancelCb

from aiogram import Router


def build_router() -> Router:
    """Build the OTP cancel and Not me router."""
    router = Router(name="auth.security")
    router.callback_query.register(cancel_otp_reset, OtpCancelCb.filter())
    router.callback_query.register(not_me, NotMeCb.filter())
    return router
