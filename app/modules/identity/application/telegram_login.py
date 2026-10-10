"""POST /v1/id/telegram/login: log in on the mini app page and link the account."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.application.link_telegram_account import LinkTelegramAccount
from app.modules.identity.application.login_result import LoginResult, SecondFactor
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.password_authenticator import (
    PasswordAuthenticator,
)
from app.modules.identity.application.passwordless_otp_check import PasswordlessOtpCheck
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import InvalidCredentialsError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.init_data_verifier import InitDataVerifier
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.ids import random_token


@dataclass(frozen=True, slots=True)
class TelegramLoginResult:
    """Linked, or a second factor is needed first (Administration)."""

    linked: bool
    login: str | None = None
    second_factor_result: LoginResult | None = None


@dataclass(frozen=True, slots=True)
class TelegramLogin:
    """Password (+ OTP for Administration) or a passwordless OTP code."""

    uow_factory: UowFactory
    verifier: InitDataVerifier
    authenticator: PasswordAuthenticator
    passwordless: PasswordlessOtpCheck
    otp: OtpService
    linker: LinkTelegramAccount
    max_age: timedelta

    async def execute(
        self,
        init_data: str,
        login: str,
        *,
        password: str | None,
        otp_code: str | None,
        ctx: RequestContext,
    ) -> TelegramLoginResult:
        """Verify initData and credentials, then link the Telegram account."""
        telegram_user = self.verifier.verify(init_data, max_age=self.max_age)
        async with self.uow_factory() as uow:
            if password is not None:
                user = await self.authenticator.authenticate(uow, login, password, ctx)
                pending = await self._admin_second_factor(uow, user, otp_code, ctx)
                if pending is not None:
                    return TelegramLoginResult(
                        linked=False, second_factor_result=pending
                    )
            elif otp_code:
                user = await self.passwordless.execute(uow, login, otp_code, ctx)
            else:
                raise InvalidCredentialsError()
            await self.linker.execute(uow, user, telegram_user, ctx)
            await uow.commit()
        return TelegramLoginResult(linked=True, login=user.login)

    async def _admin_second_factor(
        self,
        uow: IdentityUnitOfWorkPort,
        user: User,
        otp_code: str | None,
        ctx: RequestContext,
    ) -> LoginResult | None:
        """An administrator with OTP on needs a code; send one on the first attempt."""
        if not (user.is_admin and user.otp_enabled):
            return None
        if otp_code:
            await self.otp.check("tg-login", str(user.id), otp_code)
            return None
        links = await uow.telegram_links.list_for_user(user.id)
        channels = await self.otp.send(
            user, links, purpose="tg-login", subject_key=str(user.id), ctx=ctx
        )
        # The retry carries the code itself, so the ticket is only a placeholder.
        return LoginResult(
            second_factor=SecondFactor(ticket=random_token(8), channels=channels)
        )
