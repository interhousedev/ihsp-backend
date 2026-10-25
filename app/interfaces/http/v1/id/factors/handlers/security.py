"""/v1/id/me/security, /totp/*, /passkeys/*, /password-login/disable."""

from uuid import UUID

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep
from app.interfaces.http.v1.id.factors.schemas import (
    PasskeyRegisterBody,
    PasskeyRenameBody,
    PasskeyResponse,
    RecoveryCodesResponse,
    SecurityResponse,
    TotpCodeBody,
    TotpSetupResponse,
    WebAuthnOptionsResponse,
)

from fastapi import Response


async def get_security(actor: ActorDep, auth: AuthDep) -> SecurityResponse:
    """TOTP state, password sign-in switch and passkeys."""
    return SecurityResponse.of(await auth.factors.manage_passkeys.overview(actor))


async def post_totp_setup(actor: ActorDep, auth: AuthDep) -> TotpSetupResponse:
    """A new secret for the authenticator app (valid 10 minutes)."""
    setup = await auth.factors.manage_totp.start(actor)
    return TotpSetupResponse(secret=setup.secret, otpauth_uri=setup.otpauth_uri)


async def post_totp_confirm(
    body: TotpCodeBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> RecoveryCodesResponse:
    """Turn the app on with its first code; return the recovery codes."""
    codes = await auth.factors.manage_totp.confirm(actor, body.code, ctx)
    return RecoveryCodesResponse(recovery_codes=codes)


async def post_totp_disable(
    body: TotpCodeBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> SecurityResponse:
    """Turn the app off with a fresh code or a recovery code."""
    await auth.factors.manage_totp.disable(actor, body.code, ctx)
    return SecurityResponse.of(await auth.factors.manage_passkeys.overview(actor))


async def post_passkey_options(
    actor: ActorDep, auth: AuthDep
) -> WebAuthnOptionsResponse:
    """Options for navigator.credentials.create."""
    options = await auth.factors.manage_passkeys.registration_options(actor)
    return WebAuthnOptionsResponse(options=options)


async def post_passkey(
    body: PasskeyRegisterBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> PasskeyResponse:
    """Store a new passkey."""
    passkey = await auth.factors.manage_passkeys.register(
        actor, body.credential, body.name, ctx
    )
    return PasskeyResponse.of(passkey)


async def patch_passkey(
    id: UUID, body: PasskeyRenameBody, actor: ActorDep, auth: AuthDep
) -> PasskeyResponse:
    """Rename a passkey."""
    return PasskeyResponse.of(
        await auth.factors.manage_passkeys.rename(actor, id, body.name)
    )


async def delete_passkey(
    id: UUID, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Remove a passkey (not the last one while password sign-in is off)."""
    await auth.factors.manage_passkeys.delete(actor, id, ctx)
    return Response(status_code=204)


async def post_password_login_disable(
    actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> SecurityResponse:
    """Sign in with passkeys only; a password reset turns passwords back on."""
    await auth.factors.manage_passkeys.disable_password_login(actor, ctx)
    return SecurityResponse.of(await auth.factors.manage_passkeys.overview(actor))
