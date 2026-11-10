"""Vault seal status and unseal key submission (administrators, OTP step-up)."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import VAULT_UNSEAL_SUBMITTED
from app.modules.identity.domain.errors import SecondFactorRequiredError
from app.modules.identity.ports.unit_of_work import UowFactory
from app.modules.identity.ports.vault_seal import VaultSeal, VaultSealStatus
from app.shared.actor import Actor, Role
from app.shared.rate_limit import RateLimiter

from pydantic import SecretStr

ATTEMPTS = 10
WINDOW_SECONDS = 600


@dataclass(frozen=True, slots=True)
class GetVaultStatus:
    """Reports the seal state."""

    seal: VaultSeal

    async def execute(self, actor: Actor) -> VaultSealStatus:
        """Administrators only."""
        actor.require(Role.ADMIN)
        return await self.seal.status()


@dataclass(frozen=True, slots=True)
class UnsealVault:
    """Forwards one key share to Vault. The share is never stored or logged."""

    uow_factory: UowFactory
    otp: OtpService
    seal: VaultSeal
    rate_limiter: RateLimiter

    async def execute(
        self,
        actor: Actor,
        *,
        key: SecretStr,
        otp_code: str | None,
        ctx: RequestContext,
    ) -> VaultSealStatus:
        """Check the second factor, record the attempt, submit the share."""
        actor.require(Role.ADMIN)
        await self.rate_limiter.hit(
            f"vault-unseal:{actor.user_id}",
            limit=ATTEMPTS,
            window_seconds=WINDOW_SECONDS,
        )
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if not otp_code:
                raise SecondFactorRequiredError(params={"action": "vault-unseal"})
            await self.otp.check("step-up", str(user.id), otp_code)
            uow.audit(make_audit(VAULT_UNSEAL_SUBMITTED, user_id=user.id, ctx=ctx))
            await uow.commit()
        return await self.seal.submit_key(key)
