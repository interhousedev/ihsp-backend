"""POST /v1/id/me/otp/enable: send a test code to the chosen channels."""

from dataclasses import dataclass

from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import OtpChannelMissingError
from app.modules.identity.ports.otp_sender import CHANNEL_EMAIL, CHANNEL_TELEGRAM
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

PENDING_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class EnableOtp:
    """First step of UF-ID-06: choose channels and prove they work."""

    uow_factory: UowFactory
    otp: OtpService
    tickets: TicketStore

    async def execute(
        self, actor: Actor, *, via_email: bool, ctx: RequestContext
    ) -> None:
        """Send the code and remember the choice until it is confirmed."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            links = await uow.telegram_links.list_for_user(user.id)
            channels: list[str] = []
            if any(link.can_receive_otp for link in links):
                channels.append(CHANNEL_TELEGRAM)
            if via_email and user.has_verified_email:
                channels.append(CHANNEL_EMAIL)
            if via_email and not user.has_verified_email:
                raise OtpChannelMissingError(params={"reason": "email-not-verified"})
            if not channels:
                raise OtpChannelMissingError(params={"reason": "no-channel"})
            await self.tickets.put(
                f"otp-enable:{user.id}",
                {"via_email": via_email},
                ttl=PENDING_TTL_SECONDS,
            )
            await self.otp.send(
                user,
                links,
                purpose="otp-enable",
                subject_key=str(user.id),
                ctx=ctx,
                channels=channels,
            )
