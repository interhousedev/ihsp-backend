"""Password login with an EMIS ID; the client never sees the login."""

from dataclasses import dataclass

from app.modules.identity.application.log_in_with_password import LogInWithPassword
from app.modules.identity.application.login_result import LoginResult
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.resolve_emis_login import ResolveEmisLogin
from app.modules.identity.domain.emis_login import EmisLoginInvalidError
from app.modules.identity.domain.errors import InvalidCredentialsError

# No account has this login, so an unknown or malformed EMIS ID takes the same
# password path (dummy hash, same throttling) and fails like a wrong password.
NO_ACCOUNT_LOGIN = "!no-account"


@dataclass(frozen=True, slots=True)
class LogInWithEmisId:
    """Resolve the EMIS ID, then run the ordinary password login."""

    resolver: ResolveEmisLogin
    password: LogInWithPassword

    async def execute(
        self,
        challenge: str,
        emis_id: str,
        password: str,
        *,
        remember: bool,
        ctx: RequestContext,
    ) -> LoginResult:
        """Return what the password login returns; unknown IDs get its generic error."""
        try:
            login = await self.resolver.find_login(emis_id, ctx=ctx)
        except EmisLoginInvalidError:
            login = None
        try:
            return await self.password.execute(
                challenge,
                login or NO_ACCOUNT_LOGIN,
                password,
                remember=remember,
                ctx=ctx,
            )
        except InvalidCredentialsError:
            await self.resolver.record_failure(emis_id)
            raise
