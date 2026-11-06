"""POST /v1/id/me/emis-password/change: change the password in EMIS itself.

The caller proves control twice before EMIS is contacted: the current my.iht password
or a step-up code, then the current EMIS password. Passwords are never logged.
"""

from dataclasses import dataclass
from functools import partial
from uuid import UUID

from app.modules.identity.application.register_errors import (
    EmisNewPasswordRejectedError,
    EmisProfileMismatchError,
    NoEmisLinkError,
    OtpCodeInvalidError,
    WrongEmisPasswordError,
    WrongPasswordError,
    emis_errors,
)
from app.modules.identity.application.register_models import (
    AccountSnapshot,
    EmisAuthError,
    EmisPasswordRejectedError,
    EmisRequestError,
)
from app.modules.identity.application.register_ports import (
    CredentialStore,
    EmisApi,
    OtpPort,
    PasswordHasher,
    UnitOfWorkFactory,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from app.shared.notifications import AuditDraft
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

ATTEMPTS_PER_HOUR = 5
STEP_UP_PURPOSE = "step-up"  # the code POST /v1/id/me/step-up sends, keyed by user id


@dataclass(frozen=True, slots=True)
class EmisPasswordChange:
    """The passwords of one request; exactly one second factor is set."""

    current_emis_password: str
    new_emis_password: str
    account_password: str | None = None
    otp_code: str | None = None


class ChangeEmisPassword:
    """Verify both factors, change the password in EMIS, then update the secret."""

    def __init__(
        self,
        *,
        emis: EmisApi,
        store: CredentialStore,
        uow_factory: UnitOfWorkFactory,
        hasher: PasswordHasher,
        otp: OtpPort,
        rate_limiter: RateLimiter,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self._emis = emis
        self._store = store
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._otp = otp
        self._rate_limiter = rate_limiter
        self._kicker = kicker

    async def execute(self, actor: Actor, change: EmisPasswordChange) -> None:
        """Change the password, or raise a typed error and leave it unchanged."""
        actor.require(Role.STUDENT)
        await self._rate_limiter.hit(
            f"emis-password-change:{actor.user_id}",
            limit=ATTEMPTS_PER_HOUR,
            window_seconds=3600,
        )
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(actor.user_id)
        ref, emis_student_id = self._require_link(account)
        assert account is not None  # _require_link refused None
        await self._check_second_factor(account, change)
        with emis_errors():
            secret = await self._store.read(ref)
            new_password_enc = await self._store.encrypt(change.new_emis_password)
            token = await self._log_in_with_current(secret.login, change)
            profile = await self._emis.profile(token)
            if profile.emis_student_id != emis_student_id:
                raise EmisProfileMismatchError(
                    support_details=f"emis {profile.emis_student_id}"
                )
            await self._submit(token, change.new_emis_password)
            # EMIS may end the old session with the password change.
            token = await self._fresh_token(secret.login, change, token)
            await self._store.replace(
                ref,
                login=secret.login,
                password_enc=new_password_enc,
                access_token=token,
            )
        await self._finish(actor.user_id)

    async def _check_second_factor(
        self, account: AccountSnapshot, change: EmisPasswordChange
    ) -> None:
        if change.otp_code is not None:
            if not await self._otp.verify(
                STEP_UP_PURPOSE, str(account.id), change.otp_code.strip()
            ):
                raise OtpCodeInvalidError()
            return
        if (
            not change.account_password
            or not account.password_hash
            or not await self._hasher.verify(
                account.password_hash, change.account_password
            )
        ):
            raise WrongPasswordError()

    async def _log_in_with_current(self, login: str, change: EmisPasswordChange) -> str:
        try:
            return await self._emis.login(login, change.current_emis_password)
        except EmisAuthError as exc:
            raise WrongEmisPasswordError() from exc

    async def _submit(self, token: str, new_password: str) -> None:
        try:
            await self._emis.change_password(token, new_password)
        except EmisPasswordRejectedError as exc:
            raise EmisNewPasswordRejectedError() from exc

    async def _fresh_token(
        self, login: str, change: EmisPasswordChange, old_token: str
    ) -> str:
        try:
            return await self._emis.login(login, change.new_emis_password)
        except (EmisAuthError, EmisRequestError):
            log.warning("emis_relogin_after_password_change_failed")
            return old_token

    async def _finish(self, user_id: UUID) -> None:
        async with self._uow_factory() as uow:
            await uow.accounts.set_emis_status(user_id, "active")
            uow.audit(
                AuditDraft(
                    type="emis.password_changed",
                    user_id=user_id,
                    actor_id=user_id,
                )
            )
            uow.after_commit(
                partial(
                    self._kicker.kick,
                    "academic.sync_student",
                    user_id=str(user_id),
                )
            )
            await uow.commit()

    @staticmethod
    def _require_link(account: AccountSnapshot | None) -> tuple[UUID, int]:
        if (
            account is None
            or account.status is not UserStatus.ACTIVE
            or account.emis_vault_ref is None
            or account.emis_student_id is None
        ):
            raise NoEmisLinkError()
        return account.emis_vault_ref, account.emis_student_id
