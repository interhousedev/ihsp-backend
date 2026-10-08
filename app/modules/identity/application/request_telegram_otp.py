"""POST /v1/id/telegram/otp/request: send a login code from the mini app page."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.request_login_otp import RequestLoginOtp
from app.modules.identity.ports.init_data_verifier import InitDataVerifier


@dataclass(frozen=True, slots=True)
class RequestTelegramOtp:
    """The mini app has no Hydra challenge, so initData proves the caller instead."""

    verifier: InitDataVerifier
    request_login_otp: RequestLoginOtp
    max_age: timedelta

    async def execute(self, init_data: str, login: str, ctx: RequestContext) -> None:
        """Verify initData, then send a code exactly like the web OTP request."""
        self.verifier.verify(init_data, max_age=self.max_age)
        await self.request_login_otp.execute(login, ctx)
