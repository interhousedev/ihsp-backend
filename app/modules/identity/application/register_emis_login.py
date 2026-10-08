"""Check EMIS credentials for registration and reclaim (ID-1, ID-2, ID-3)."""

from dataclasses import dataclass

from app.modules.identity.application.register_errors import (
    WrongInstitutionError,
    emis_errors,
)
from app.modules.identity.application.register_ports import CredentialStore, EmisApi
from app.shared.contracts.emis import EmisProfile
from app.shared.rate_limit import RateLimiter

REG_IP_LIMIT = 10
REG_GLOBAL_LIMIT = 300
REG_WINDOW_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class VerifiedEmisAccount:
    """EMIS accepted the credentials; nothing is stored yet."""

    emis_login: str
    password_enc: str
    token: str
    token_enc: str
    profile: EmisProfile


class VerifyEmisCredentials:
    """Rate limit, encrypt the password, log in to EMIS and load the profile."""

    def __init__(
        self,
        *,
        emis: EmisApi,
        store: CredentialStore,
        rate_limiter: RateLimiter,
        institution_id: int,
    ) -> None:
        """Store the collaborators and the lyceum's EMIS institution id."""
        self._emis = emis
        self._store = store
        self._rate_limiter = rate_limiter
        self._institution_id = institution_id

    async def execute(
        self, *, emis_login: str, emis_password: str, ip: str | None
    ) -> VerifiedEmisAccount:
        """Return the verified account or raise a typed error.

        Every attempt counts toward the limits, also the failed ones, because the
        answer reveals whether EMIS credentials are valid.
        """
        await self._check_limits(ip)
        login = emis_login.strip()
        with emis_errors():
            password_enc = await self._store.encrypt(emis_password)  # before EMIS
            token = await self._emis.login(login, emis_password)
            token_enc = await self._store.encrypt(token)
            profile = await self._emis.profile(token)
        if profile.institution_id != self._institution_id:
            raise WrongInstitutionError(
                support_details=f"institution {profile.institution_id}"
            )
        return VerifiedEmisAccount(
            emis_login=login,
            password_enc=password_enc,
            token=token,
            token_enc=token_enc,
            profile=profile,
        )

    async def _check_limits(self, ip: str | None) -> None:
        await self._rate_limiter.hit(
            f"reg-ip:{ip or 'unknown'}",
            limit=REG_IP_LIMIT,
            window_seconds=REG_WINDOW_SECONDS,
        )
        await self._rate_limiter.hit(
            "reg-global", limit=REG_GLOBAL_LIMIT, window_seconds=REG_WINDOW_SECONDS
        )
