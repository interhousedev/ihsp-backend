"""Check a login and password with throttling, audit and the failure notice."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import LOGIN_FAILED
from app.modules.identity.domain.errors import InvalidCredentialsError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.login_throttle import LoginThrottle
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort
from app.shared.clock import Clock
from app.shared.notifications import NotificationDraft, NotificationType

NOTIFY_AFTER_FAILURES = 5


@dataclass(frozen=True, slots=True)
class PasswordAuthenticator:
    """Shared by the web login and the Telegram mini app login."""

    hasher: PasswordHasher
    throttle: LoginThrottle
    clock: Clock

    async def authenticate(
        self,
        uow: IdentityUnitOfWorkPort,
        login: str,
        password: str,
        ctx: RequestContext,
        *,
        allow_pending_deletion: bool = False,
    ) -> User:
        """Return the active user or raise InvalidCredentialsError / AccountLockedError.

        Failures are committed (audit, counters) before the error is raised. With
        ``allow_pending_deletion`` an account scheduled for deletion is returned too
        (the web login then offers to restore it).
        """
        await self.throttle.check(login, ctx.throttle_ip)
        user = await uow.users.get_by_login(login)
        if user is not None:
            await self.throttle.check_account(user.id)
        stored = user.password_hash if user else None
        # The hash is always verified (a dummy one for unknown logins) so the
        # answer takes the same time whether or not the account exists.
        ok = await self.hasher.verify(stored, password)
        if user is None or not ok:
            await self._record_failure(uow, login, user, ctx)
            raise InvalidCredentialsError()
        pending_ok = allow_pending_deletion and user.is_pending_deletion
        if not user.is_active and not pending_ok:
            uow.audit(
                make_audit(
                    LOGIN_FAILED, user_id=user.id, ctx=ctx, reason=user.status.value
                )
            )
            await uow.commit()
            reason = {"reason": "blocked"} if user.status.value == "blocked" else {}
            raise InvalidCredentialsError(params=reason)
        await self.throttle.reset(login, ctx.throttle_ip)
        if stored and self.hasher.needs_rehash(stored):
            user.password_hash = await self.hasher.hash(password)
            await uow.users.save(user)
        return user

    async def _record_failure(
        self,
        uow: IdentityUnitOfWorkPort,
        login: str,
        user: User | None,
        ctx: RequestContext,
    ) -> None:
        counts = await self.throttle.record_failure(
            login, ctx.throttle_ip, user.id if user else None
        )
        if user is None:
            return
        uow.audit(make_audit(LOGIN_FAILED, user_id=user.id, ctx=ctx, reason="password"))
        if counts.for_account == NOTIFY_AFTER_FAILURES:
            hour = self.clock.now().strftime("%Y%m%d%H")
            uow.notify(
                NotificationDraft(
                    user_id=user.id,
                    type=NotificationType.LOGIN_FAILURES,
                    payload={"count": counts.for_account, "ip": ctx.valid_ip},
                    dedupe_key=f"login-failures:{user.id}:{hour}",
                )
            )
        await uow.commit()
