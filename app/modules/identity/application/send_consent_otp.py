"""POST /v1/id/consent/otp: send the step-up code to the subject of a consent."""

from dataclasses import dataclass

from app.modules.identity.application.consent_support import mcp_server, parse_uuid
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.otp_service import (
    OtpService,
    channels_with_email_fallback,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.client_policy import is_first_party
from app.modules.identity.domain.errors import UserNotFoundError
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.rate_limit import RateLimiter


@dataclass(frozen=True, slots=True)
class SendConsentOtp:
    """The consent page has no bearer token, so the challenge identifies the user."""

    uow_factory: UowFactory
    hydra: HydraGateway
    otp: OtpService
    rate_limiter: RateLimiter

    async def execute(self, challenge: str, ctx: RequestContext) -> list[str]:
        """Send the step-up code (purpose step-up, key = user id); return channels."""
        request = await self.hydra.get_consent_request(challenge)
        user_id = parse_uuid(request.subject)
        if user_id is None or is_first_party(request.client.client_id):
            raise UserNotFoundError(params={"user_id": request.subject})
        mcp_server(request)  # refuses requests that do not name an MCP server
        await self.rate_limiter.hit(
            f"consent-otp:{user_id}", limit=5, window_seconds=3600
        )
        await self.rate_limiter.hit(
            f"consent-otp-ip:{ctx.throttle_ip}", limit=20, window_seconds=3600
        )
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            links = await uow.telegram_links.list_for_user(user.id)
            return await self.otp.send(
                user,
                links,
                purpose="step-up",
                subject_key=str(user.id),
                ctx=ctx,
                channels=channels_with_email_fallback(user, links),
            )
