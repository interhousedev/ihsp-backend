"""Issue, deliver and check one-time codes for a user."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import OtpChannelMissingError, OtpInvalidError
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.domain.user import User
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.otp_sender import (
    CHANNEL_EMAIL,
    CHANNEL_TELEGRAM,
    OtpContext,
    OtpSender,
)
from app.modules.identity.ports.otp_store import OtpStore


def channels_for(user: User, links: Sequence[TelegramLink]) -> list[str]:
    """OTP channels of an account: Telegram links with delivery on, email if chosen.

    Administration accounts fall back to the verified recovery email so the
    mandatory second factor can never lock them out (ID-11).
    """
    channels: list[str] = []
    if any(link.can_receive_otp for link in links):
        channels.append(CHANNEL_TELEGRAM)
    if user.otp_via_email and user.has_verified_email:
        channels.append(CHANNEL_EMAIL)
    if not channels and user.is_admin and user.has_verified_email:
        channels.append(CHANNEL_EMAIL)
    return channels


def channels_with_email_fallback(
    user: User, links: Sequence[TelegramLink]
) -> list[str]:
    """Like channels_for, but a verified recovery email is used when nothing else is."""
    channels = channels_for(user, links)
    if not channels and user.has_verified_email:
        channels.append(CHANNEL_EMAIL)
    return channels


@dataclass(frozen=True, slots=True)
class OtpService:
    """Shared by every use case that sends or checks a code."""

    otp_store: OtpStore
    otp_sender: OtpSender
    email: EmailSender

    async def send(
        self,
        user: User,
        links: Sequence[TelegramLink],
        *,
        purpose: str,
        subject_key: str,
        ctx: RequestContext,
        channels: Sequence[str] | None = None,
    ) -> list[str]:
        """Issue a code and deliver it; return the channels used.

        Raises:
            OtpChannelMissingError: the account has no way to receive a code.
            RateLimitedError: a code was sent less than 60 seconds ago.
        """
        chosen = list(channels) if channels is not None else channels_for(user, links)
        if not chosen:
            raise OtpChannelMissingError(params={"user_id": str(user.id)})
        code = await self.otp_store.issue(purpose, subject_key)
        await self.otp_sender.send_code(
            user.to_ref(),
            code,
            purpose=purpose,
            channels=chosen,
            context=OtpContext(ip=ctx.valid_ip, user_agent=ctx.device or None),
        )
        return chosen

    async def send_to_email(
        self, address: str, *, purpose: str, subject_key: str, locale: str
    ) -> None:
        """Issue a code and email it to an address that is not yet a recovery email."""
        code = await self.otp_store.issue(purpose, subject_key)
        params: dict[str, Any] = {"code": code, "purpose": purpose}
        await self.email.send(address, "otp", params, locale)

    async def check(self, purpose: str, subject_key: str, code: str) -> None:
        """Verify a code or raise OtpInvalidError with the attempts left."""
        if await self.otp_store.verify(purpose, subject_key, code):
            return
        left = await self.otp_store.attempts_left(purpose, subject_key)
        raise OtpInvalidError(params={"attempts_left": left})
