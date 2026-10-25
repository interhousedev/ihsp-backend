"""POST /v1/id/me/step-up: send a code that authorises one sensitive action."""

from dataclasses import dataclass

from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.otp_service import (
    OtpService,
    channels_with_email_fallback,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class StepUp:
    """Used before Administration connectors and before deleting an account."""

    uow_factory: UowFactory
    otp: OtpService

    async def execute(self, actor: Actor, ctx: RequestContext) -> list[str]:
        """Send the code (purpose step-up, key = user id); return the channels."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            links = await uow.telegram_links.list_for_user(user.id)
            return await self.otp.send(
                user,
                links,
                purpose="step-up",
                subject_key=str(user.id),
                ctx=ctx,
                channels=channels_with_email_fallback(user, links),
            )
