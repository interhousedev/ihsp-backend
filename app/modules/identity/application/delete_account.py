"""Delete a student's own account (UF-ID-16, ID-9, ID-29)."""

from datetime import date, timedelta
from functools import partial

from app.modules.identity.application.destroy_emis_secret import DestroyEmisSecret
from app.modules.identity.application.register_errors import (
    DeleteForbiddenError,
    OtpCodeInvalidError,
    WrongPasswordError,
)
from app.modules.identity.application.register_models import (
    AccountSnapshot,
    CredentialStoreError,
)
from app.modules.identity.application.register_ports import (
    AccountRevokerPort,
    EmailSenderPort,
    OtpPort,
    PasswordHasher,
    UnitOfWorkFactory,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import AcademicEnrollment
from app.shared.contracts.identity import UserStatus
from app.shared.notifications import AuditDraft
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

RETENTION_DAYS = 30
STEP_UP_PURPOSE = "step-up"  # the code POST /v1/id/me/step-up sends, keyed by user id


class DeleteAccount:
    """Mark the account deleted, revoke everything, destroy the secret."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        hasher: PasswordHasher,
        otp: OtpPort,
        revoker: AccountRevokerPort,
        enrollment: AcademicEnrollment,
        destroy_secret: DestroyEmisSecret,
        email_sender: EmailSenderPort,
        kicker: TaskKicker,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._otp = otp
        self._revoker = revoker
        self._enrollment = enrollment
        self._destroy_secret = destroy_secret
        self._email_sender = email_sender
        self._kicker = kicker
        self._clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        password: str,
        otp_code: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> date:
        """Check the password (and the step-up code), delete, return ``closes_on``."""
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(actor.user_id)
        account = self._require_deletable(account)
        await self._check_password(account, password)
        await self._check_otp(account, otp_code)
        closes_on = local_today(self._clock) + timedelta(days=RETENTION_DAYS)
        await self._mark_deleted(account, ip, user_agent)
        # mark_left first: it queues the account_closing notice before the links go.
        await self._enrollment.mark_left(account.id, reason="deleted")
        await self._revoker.revoke_everything(account.id)
        await self._destroy_secret_now(account)
        await self._send_notice(account, closes_on)
        return closes_on

    @staticmethod
    def _require_deletable(account: AccountSnapshot | None) -> AccountSnapshot:
        if account is None or account.status is not UserStatus.ACTIVE:
            raise DeleteForbiddenError(support_details="account is not active")
        if account.roles != frozenset({Role.STUDENT}):
            raise DeleteForbiddenError(
                support_details="staff accounts are closed by an administrator"
            )
        return account

    async def _check_password(self, account: AccountSnapshot, password: str) -> None:
        if not account.password_hash or not await self._hasher.verify(
            account.password_hash, password
        ):
            raise WrongPasswordError()

    async def _check_otp(self, account: AccountSnapshot, otp_code: str | None) -> None:
        if not account.otp_enabled:
            return
        if not otp_code or not await self._otp.verify(
            STEP_UP_PURPOSE, str(account.id), otp_code.strip()
        ):
            raise OtpCodeInvalidError()

    async def _mark_deleted(
        self, account: AccountSnapshot, ip: str | None, user_agent: str | None
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.accounts.mark_deleted(account.id, self._clock.now())
            uow.audit(
                AuditDraft(
                    type="account.deleted",
                    user_id=account.id,
                    actor_id=account.id,
                    ip=ip,
                    user_agent=user_agent,
                )
            )
            for task in ("files.delete_owner", "links.revoke_owner"):
                uow.after_commit(
                    partial(self._kicker.kick, task, user_id=str(account.id))
                )
            await uow.commit()

    async def _destroy_secret_now(self, account: AccountSnapshot) -> None:
        """Destroy at once; if Vault is down the retrying task finishes the job."""
        try:
            await self._destroy_secret.execute(account.id)
        except CredentialStoreError:
            log.warning("vault destroy failed, retrying later", user=str(account.id))
            await self._kicker.kick(
                "identity.destroy_emis_secret", user_id=str(account.id)
            )

    async def _send_notice(self, account: AccountSnapshot, closes_on: date) -> None:
        """Email the recovery address; a mail failure must not undo the deletion."""
        if not account.recovery_email:
            return
        try:
            await self._email_sender.send(
                account.recovery_email,
                "notice",
                {
                    "text_key": "id-mail-deleted-notice",
                    "text_params": {"closes_on": closes_on.isoformat()},
                },
                account.locale,
            )
        except Exception:
            log.exception("deletion notice failed", user=str(account.id))
