"""TOTP codes, recovery codes and helpers shared by the sign-in factor use cases."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.modules.identity.domain.factors import UserFactors
from app.modules.identity.ports.secret_cipher import SecretCipher
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort
from app.shared.clock import Clock

import pyotp

TOTP_ISSUER = "IHT ID"
TOTP_STEP_SECONDS = 30
TOTP_WINDOW = 1
"""One step either side is accepted (clock drift of the phone)."""
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"

FactorUsed = Literal["totp", "recovery"]


def new_totp_secret() -> str:
    """A random base32 secret (160 bits)."""
    return pyotp.random_base32(32)


def totp_uri(secret: str, account: str) -> str:
    """The otpauth:// URI the authenticator app scans."""
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=TOTP_ISSUER)


def match_totp(
    secret: str, code: str, now: datetime, last_step: int | None
) -> int | None:
    """Return the matching step (±1) not used before, or None."""
    code = code.strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = int(now.timestamp()) // TOTP_STEP_SECONDS
    for step in range(current - TOTP_WINDOW, current + TOTP_WINDOW + 1):
        if hmac.compare_digest(totp.at(step * TOTP_STEP_SECONDS), code):
            if last_step is not None and step <= last_step:
                return None  # replay of a code already accepted
            return step
    return None


def _normalize_recovery(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str) -> str:
    """SHA-256 of the normalized code (the codes have 50 bits of entropy)."""
    return hashlib.sha256(_normalize_recovery(code).encode()).hexdigest()


def new_recovery_codes() -> list[str]:
    """Ten one-time codes such as ``k7mq-2xpa``."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


@dataclass(frozen=True, slots=True)
class TotpVerifier:
    """Checks a TOTP or recovery code against stored factors and updates them."""

    cipher: SecretCipher
    clock: Clock

    async def verify(
        self, factors: UserFactors, code: str, *, allow_recovery: bool = True
    ) -> FactorUsed | None:
        """Return what matched; the caller saves ``factors`` (step or used code)."""
        if not factors.totp_enabled or factors.totp_secret_enc is None:
            return None
        secret = await self.cipher.decrypt(factors.totp_secret_enc)
        step = match_totp(secret, code, self.clock.now(), factors.totp_last_step)
        if step is not None:
            factors.totp_last_step = step
            return "totp"
        if not allow_recovery:
            return None
        digest = hash_recovery_code(code)
        for stored in factors.recovery_code_hashes:
            if hmac.compare_digest(stored, digest):
                factors.recovery_code_hashes = [
                    h for h in factors.recovery_code_hashes if h != stored
                ]
                return "recovery"
        return None


async def load_factors(uow: IdentityUnitOfWorkPort, user_id: UUID) -> UserFactors:
    """The stored factors or an empty record."""
    return await uow.factors.get(user_id) or UserFactors(user_id=user_id)


async def enable_password_login(uow: IdentityUnitOfWorkPort, user_id: UUID) -> None:
    """A new password was set: password sign-in works again."""
    factors = await uow.factors.get(user_id)
    if factors is not None and factors.password_login_disabled:
        factors.password_login_disabled = False
        await uow.factors.save(factors)


async def reset_totp(uow: IdentityUnitOfWorkPort, user_id: UUID) -> None:
    """The phone is lost: forget the authenticator app (OTP resets do this too)."""
    factors = await uow.factors.get(user_id)
    if factors is not None and factors.totp_enabled:
        factors.clear_totp()
        await uow.factors.save(factors)
