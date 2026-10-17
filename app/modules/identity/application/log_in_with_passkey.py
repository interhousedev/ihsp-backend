"""POST /v1/id/login/passkey{,/options}: sign in with a passkey."""

import base64
from dataclasses import dataclass
from typing import Any

from app.modules.identity.application.login_result import LoginResult
from app.modules.identity.application.manage_passkeys import (
    CEREMONY_TTL_SECONDS,
    decode_challenge,
    encode_challenge,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.restore_account import RestoreOffer
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.errors import PasskeyInvalidError, RoleMissingError
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.modules.identity.ports.webauthn import WebAuthn
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

IP_LIMIT_PER_HOUR = 300
AMR = ["hwk"]  # RFC 8176: proof of possession of a hardware-secured key


def _b64url(value: object) -> bytes:
    text = str(value)
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as exc:
        raise PasskeyInvalidError(params={"reason": "malformed"}) from exc


@dataclass(frozen=True, slots=True)
class LogInWithPasskey:
    """Discoverable credentials: the passkey names the user; user verification on."""

    uow_factory: UowFactory
    hydra: HydraGateway
    webauthn: WebAuthn
    tickets: TicketStore
    starter: LoginSessionStarter
    rate_limiter: RateLimiter
    clock: Clock
    restore_offer: RestoreOffer | None = None

    async def options(self, challenge: str, ctx: RequestContext) -> dict[str, Any]:
        """Options for navigator.credentials.get, bound to the Hydra challenge."""
        await self._limit(ctx)
        request = await self.hydra.get_login_request(challenge)
        ceremony = self.webauthn.authentication_options()
        await self.tickets.put(
            f"passkey-auth:{request.challenge}",
            {"challenge": encode_challenge(ceremony.challenge)},
            ttl=CEREMONY_TTL_SECONDS,
        )
        return ceremony.options

    async def execute(
        self,
        challenge: str,
        credential: dict[str, Any],
        *,
        remember: bool,
        ctx: RequestContext,
    ) -> LoginResult:
        """Verify the assertion and accept the Hydra login like a password login."""
        await self._limit(ctx)
        key = f"passkey-auth:{challenge}"
        pending = await self.tickets.get(key)
        if pending is None:
            raise PasskeyInvalidError(params={"reason": "expired"})
        await self.tickets.delete(key)  # one assertion per options call
        request = await self.hydra.get_login_request(challenge)
        credential_id = _b64url(credential.get("rawId") or credential.get("id") or "")
        async with self.uow_factory() as uow:
            passkey = await uow.factors.get_passkey_by_credential(credential_id)
            if passkey is None:
                raise PasskeyInvalidError(params={"reason": "unknown"})
            handle = (credential.get("response") or {}).get("userHandle")
            if handle and _b64url(handle) != passkey.user_id.bytes:
                raise PasskeyInvalidError(params={"reason": "user-handle"})
            verified = self.webauthn.verify_authentication(
                credential,
                decode_challenge(pending["challenge"]),
                public_key=passkey.public_key,
                sign_count=passkey.sign_count,
            )
            user = await uow.users.get(passkey.user_id)
            pending_ok = (
                user is not None
                and self.restore_offer is not None
                and user.is_pending_deletion
            )
            if user is None or not (user.is_active or pending_ok):
                raise PasskeyInvalidError(params={"reason": "inactive"})
            if not may_use_client(request.client.client_id, user.roles):
                raise RoleMissingError(params={"client_id": request.client.client_id})
            passkey.sign_count = verified.new_sign_count
            passkey.backed_up = verified.backed_up
            passkey.last_used_at = self.clock.now()
            await uow.factors.save_passkey(passkey)
            if pending_ok and self.restore_offer is not None:
                await uow.commit()
                return await self.restore_offer.make(
                    user, request.challenge, amr=AMR, remember=remember
                )
            redirect = await self.starter.start(
                uow, request, user, amr=AMR, mfa=True, ctx=ctx, remember=remember
            )
        return LoginResult(redirect_to=redirect)

    async def _limit(self, ctx: RequestContext) -> None:
        await self.rate_limiter.hit(
            f"login-passkey-ip:{ctx.throttle_ip}",
            limit=IP_LIMIT_PER_HOUR,
            window_seconds=3600,
        )
