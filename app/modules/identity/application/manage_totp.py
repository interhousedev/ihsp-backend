"""POST /v1/id/me/totp/{setup,confirm,disable}: the authenticator app."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.factor_support import (
    TotpVerifier,
    hash_recovery_code,
    load_factors,
    match_totp,
    new_recovery_codes,
    new_totp_secret,
    totp_uri,
)
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import TOTP_DISABLED, TOTP_ENABLED
from app.modules.identity.domain.errors import OtpInvalidError, TotpStateError
from app.modules.identity.ports.secret_cipher import SecretCipher
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter

SETUP_TTL_SECONDS = 600
ATTEMPTS_PER_15_MINUTES = 10


@dataclass(frozen=True, slots=True)
class TotpSetup:
    """The secret to scan: ``otpauth_uri`` for the QR code, ``secret`` to type."""

    secret: str
    otpauth_uri: str


@dataclass(frozen=True, slots=True)
class ManageTotp:
    """Enable (two steps) and disable the authenticator app."""

    uow_factory: UowFactory
    cipher: SecretCipher
    tickets: TicketStore
    verifier: TotpVerifier
    rate_limiter: RateLimiter
    clock: Clock

    async def start(self, actor: Actor) -> TotpSetup:
        """Make a new secret; it is kept (encrypted) for 10 minutes until confirmed."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            factors = await load_factors(uow, user.id)
        if factors.totp_enabled:
            raise TotpStateError(params={"enabled": True})
        secret = new_totp_secret()
        await self.tickets.put(
            f"totp-setup:{user.id}",
            {"secret_enc": await self.cipher.encrypt(secret)},
            ttl=SETUP_TTL_SECONDS,
        )
        return TotpSetup(
            secret=secret, otpauth_uri=totp_uri(secret, user.login or str(user.id))
        )

    async def confirm(self, actor: Actor, code: str, ctx: RequestContext) -> list[str]:
        """Check the first code; return the one-time recovery codes (shown once)."""
        await self._limit(actor)
        pending = await self.tickets.get(f"totp-setup:{actor.user_id}")
        if pending is None:
            raise OtpInvalidError(params={"attempts_left": 0})
        secret_enc = str(pending["secret_enc"])
        secret = await self.cipher.decrypt(secret_enc)
        step = match_totp(secret, code, self.clock.now(), None)
        if step is None:
            raise OtpInvalidError(params={"attempts_left": 1})
        codes = new_recovery_codes()
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            factors = await load_factors(uow, user.id)
            if factors.totp_enabled:
                raise TotpStateError(params={"enabled": True})
            factors.totp_secret_enc = secret_enc
            factors.totp_enabled_at = self.clock.now()
            factors.totp_last_step = step
            factors.recovery_code_hashes = [hash_recovery_code(c) for c in codes]
            await uow.factors.save(factors)
            uow.audit(make_audit(TOTP_ENABLED, user_id=user.id, ctx=ctx))
            await uow.commit()
        await self.tickets.delete(f"totp-setup:{actor.user_id}")
        return codes

    async def disable(self, actor: Actor, code: str, ctx: RequestContext) -> None:
        """Turn the app off with a fresh code (or a recovery code)."""
        await self._limit(actor)
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            factors = await load_factors(uow, user.id)
            if not factors.totp_enabled:
                raise TotpStateError(params={"enabled": False})
            if await self.verifier.verify(factors, code) is None:
                raise OtpInvalidError(params={"attempts_left": 1})
            factors.clear_totp()
            await uow.factors.save(factors)
            uow.audit(make_audit(TOTP_DISABLED, user_id=user.id, ctx=ctx))
            await uow.commit()

    async def _limit(self, actor: Actor) -> None:
        await self.rate_limiter.hit(
            f"totp-manage:{actor.user_id}",
            limit=ATTEMPTS_PER_15_MINUTES,
            window_seconds=900,
        )
