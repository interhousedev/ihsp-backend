"""The EMIS ID lookup: the login of the active account linked to a student or teacher.

Used by the check step (POST /v1/id/login/emis/resolve, answers only "registered")
and by the password login with an EMIS ID, which never shows the login to the client.
The lookup is throttled per IP (a minute and an hour window); an identifier is
blocked only after failed password logins with it (record_failure), so a lookup
alone cannot lock a student out. Lookups are audited with a masked ID and padded to
a fixed minimum duration.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.register_ports import EmisUnitOfWork
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.emis_login import (
    EMIS_LOGIN_LOOKUP,
    EmisLoginInvalidError,
    EmisLoginNotFoundError,
    emis_id_fingerprint,
    mask_emis_id,
    validate_emis_id,
)
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.base_error import RateLimitedError
from app.shared.contracts.identity import UserStatus
from app.shared.rate_limit import RateLimiter

RESPONSE_FLOOR_SECONDS = 0.3
IP_LIMIT_PER_MINUTE = 5
IP_LIMIT_PER_HOUR = 20
ID_FAILURES_PER_HOUR = 10

OUTCOME_FOUND = "found"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_RATE_LIMITED = "rate_limited"


def _id_key(emis_id: str) -> str:
    return f"emis-login-id:{emis_id_fingerprint(emis_id)}"


@dataclass(frozen=True, slots=True)
class ResolvedEmisLogin:
    """The login of the account; internal, never sent to the client."""

    login: str


@dataclass(frozen=True, slots=True)
class ResolveEmisLogin:
    """Validate, throttle, look the EMIS ID up (students, then teachers), audit, pad."""

    uow_factory: Callable[[], EmisUnitOfWork]
    teacher_uow_factory: UowFactory
    rate_limiter: RateLimiter
    floor_seconds: float = RESPONSE_FLOOR_SECONDS
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def execute(
        self, raw_emis_id: str, *, ctx: RequestContext
    ) -> ResolvedEmisLogin:
        """Return the login of the active account, or raise EmisLoginNotFoundError."""
        login = await self.find_login(raw_emis_id, ctx=ctx)
        if login is None:
            raise EmisLoginNotFoundError()
        return ResolvedEmisLogin(login=login)

    async def find_login(self, raw_emis_id: str, *, ctx: RequestContext) -> str | None:
        """Return the login of the active account, or None; malformed IDs raise."""
        emis_id = validate_emis_id(raw_emis_id)
        started = self.monotonic()
        try:
            return await self._lookup(emis_id, ctx)
        finally:
            pause = self.floor_seconds - (self.monotonic() - started)
            if pause > 0:
                await self.sleep(pause)

    async def _lookup(self, emis_id: str, ctx: RequestContext) -> str | None:
        try:
            await self._check_limits(emis_id, ctx)
        except RateLimitedError:
            await self._audit(emis_id, ctx, OUTCOME_RATE_LIMITED, None)
            raise
        found = await self._find_account(emis_id)
        if found is None:
            await self._audit(emis_id, ctx, OUTCOME_NOT_FOUND, None)
            return None
        user_id, login = found
        await self._audit(emis_id, ctx, OUTCOME_FOUND, user_id)
        return login

    async def _find_account(self, emis_id: str) -> tuple[UUID, str] | None:
        async with self.uow_factory() as uow:
            account = await uow.accounts.get_by_emis_student_id(int(emis_id))
        if (
            account is not None
            and account.status == UserStatus.ACTIVE
            and account.login
        ):
            return account.id, account.login
        async with self.teacher_uow_factory() as identity:
            user = await identity.users.get_by_emis_teacher_id(int(emis_id))
        if user is not None and user.is_active and user.login:
            return user.id, user.login
        return None

    async def _check_limits(self, emis_id: str, ctx: RequestContext) -> None:
        ip = ctx.throttle_ip
        await self.rate_limiter.hit(
            f"emis-login-ip-min:{ip}", limit=IP_LIMIT_PER_MINUTE, window_seconds=60
        )
        await self.rate_limiter.hit(
            f"emis-login-ip-hour:{ip}", limit=IP_LIMIT_PER_HOUR, window_seconds=3600
        )
        # Only failed logins count (record_failure); a lookup never blocks an ID.
        await self.rate_limiter.check(_id_key(emis_id), limit=ID_FAILURES_PER_HOUR)

    async def record_failure(self, raw_emis_id: str) -> None:
        """Count one failed login with this EMIS ID; malformed IDs are ignored."""
        try:
            emis_id = validate_emis_id(raw_emis_id)
        except EmisLoginInvalidError:
            return
        await self.rate_limiter.hit(
            _id_key(emis_id), limit=ID_FAILURES_PER_HOUR, window_seconds=3600
        )

    async def _audit(
        self, emis_id: str, ctx: RequestContext, outcome: str, user_id: UUID | None
    ) -> None:
        async with self.uow_factory() as uow:
            uow.audit(
                make_audit(
                    EMIS_LOGIN_LOOKUP,
                    user_id=user_id,
                    ctx=ctx,
                    emis_id=mask_emis_id(emis_id),
                    outcome=outcome,
                )
            )
            await uow.commit()
