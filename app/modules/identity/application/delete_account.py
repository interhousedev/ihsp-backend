"""Delete a student's own account (UF-ID-16, ID-9, ID-29).

The deletion is soft: the account becomes ``pending_deletion`` and every session
is revoked. Logging in again before the purge offers to restore it; the daily job
``identity.purge_deleted_users`` removes the data after the retention period.
"""

from collections.abc import Awaitable, Callable
from datetime import date
from uuid import UUID

from app.modules.identity.application.deletion_notice import deletion_date
from app.modules.identity.application.register_errors import (
    DeleteForbiddenError,
    OtpCodeInvalidError,
    WrongPasswordError,
)
from app.modules.identity.application.register_models import AccountSnapshot
from app.modules.identity.application.register_ports import (
    AccountRevokerPort,
    EmailSenderPort,
    OtpPort,
    PasswordHasher,
    UnitOfWorkFactory,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.contracts.identity import UserStatus
from app.shared.notifications import AuditDraft

import structlog

log = structlog.get_logger(__name__)

RETENTION_DAYS = 30
STEP_UP_PURPOSE = "step-up"  # the code POST /v1/id/me/step-up sends, keyed by user id

TelegramNotice = Callable[[UUID, date], Awaitable[None]]


class DeleteAccount:
    """Mark the account pending deletion, revoke every session, tell the owner."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        hasher: PasswordHasher,
        otp: OtpPort,
        revoker: AccountRevokerPort,
        email_sender: EmailSenderPort,
        clock: Clock,
        telegram_notice: TelegramNotice | None = None,
        retention_days: int = RETENTION_DAYS,
    ) -> None:
        """Store the collaborators."""
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._otp = otp
        self._revoker = revoker
        self._email_sender = email_sender
        self._clock = clock
        self._telegram_notice = telegram_notice
        self._retention_days = retention_days

    async def execute(
        self,
        actor: Actor,
        *,
        password: str,
        otp_code: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> date:
        """Check the password (and the step-up code), schedule; return ``closes_on``."""
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(actor.user_id)
        account = self._require_deletable(account)
        await self._check_password(account, password)
        await self._check_otp(account, otp_code)
        now = self._clock.now()
        closes_on = deletion_date(now, self._retention_days)
        async with self._uow_factory() as uow:
            await uow.accounts.mark_pending_deletion(account.id, now)
            uow.audit(
                AuditDraft(
                    type="account.deletion_requested",
                    user_id=account.id,
                    actor_id=account.id,
                    ip=ip,
                    user_agent=user_agent,
                    metadata={"deletes_on": closes_on.isoformat()},
                )
            )
            await uow.commit()
        # Telegram links stay: they carry the notice and survive a restore.
        await self._revoker.revoke_everything(account.id, keep_telegram=True)
        await self._send_notices(account, closes_on)
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

    async def _send_notices(self, account: AccountSnapshot, closes_on: date) -> None:
        """Telegram and the recovery address; a failure never undoes the request."""
        if self._telegram_notice is not None:
            try:
                await self._telegram_notice(account.id, closes_on)
            except Exception:
                log.exception("deletion telegram notice failed", user=str(account.id))
        if not account.recovery_email:
            return
        try:
            await self._email_sender.send(
                account.recovery_email,
                "notice",
                {
                    "text_key": "id-mail-deletion-scheduled",
                    "text_params": {"closes_on": closes_on.isoformat()},
                },
                account.locale,
            )
        except Exception:
            log.exception("deletion notice failed", user=str(account.id))
