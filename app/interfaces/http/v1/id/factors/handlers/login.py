"""POST /v1/id/login/totp and /v1/id/login/passkey{,/options}."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.factors.schemas import (
    PasskeyLoginBody,
    PasskeyOptionsBody,
    TotpLoginBody,
    WebAuthnOptionsResponse,
)
from app.interfaces.http.v1.id.login.schemas import LoginResultResponse


async def post_login_totp(
    body: TotpLoginBody, auth: AuthDep, ctx: CtxDep
) -> LoginResultResponse:
    """The authenticator code (or a recovery code) after the password."""
    result = await auth.factors.log_in_with_totp.execute(
        body.login_challenge, body.ticket, body.code, ctx=ctx
    )
    return LoginResultResponse.of(result)


async def post_login_passkey_options(
    body: PasskeyOptionsBody, auth: AuthDep, ctx: CtxDep
) -> WebAuthnOptionsResponse:
    """Options for navigator.credentials.get (also for conditional UI)."""
    options = await auth.factors.log_in_with_passkey.options(body.login_challenge, ctx)
    return WebAuthnOptionsResponse(options=options)


async def post_login_passkey(
    body: PasskeyLoginBody, auth: AuthDep, ctx: CtxDep
) -> LoginResultResponse:
    """Verify the passkey and accept the login."""
    result = await auth.factors.log_in_with_passkey.execute(
        body.login_challenge, body.credential, remember=body.remember, ctx=ctx
    )
    return LoginResultResponse.of(result)
