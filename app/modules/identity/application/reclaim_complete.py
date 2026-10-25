"""Finish reclaiming an account: new password and email, everything revoked (ID-28)."""

from app.modules.identity.application.reclaim_start import check_reclaimable
from app.modules.identity.application.register_errors import (
    EmailInUseError,
    EmailNotSetError,
    RegistrationExpiredError,
    UserNotFoundError,
    WeakPasswordError,
    emis_errors,
)
from app.modules.identity.application.register_models import (
    AccountSnapshot,
    PendingReclaim,
)
from app.modules.identity.application.register_ports import (
    AccountRevokerPort,
    CredentialStore,
    EmailSenderPort,
    EmisUnitOfWork,
    PasswordHasher,
    PendingStore,
    UnitOfWorkFactory,
)
from app.modules.identity.application.register_verification import EmailVerifier
from app.modules.identity.domain.password_policy import check_password
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft

import structlog

log = structlog.get_logger(__name__)


class CompleteReclaim:
    """Replace the password, the recovery email and the Vault secret."""

    def __init__(
        self,
        *,
        pending: PendingStore[PendingReclaim],
        verifier: EmailVerifier,
        store: CredentialStore,
        hasher: PasswordHasher,
        uow_factory: UnitOfWorkFactory,
        revoker: AccountRevokerPort,
        email_sender: EmailSenderPort,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self._pending = pending
        self._verifier = verifier
        self._store = store
        self._hasher = hasher
        self._uow_factory = uow_factory
        self._revoker = revoker
        self._email_sender = email_sender
        self._clock = clock

    async def execute(
        self,
        *,
        reclaim_token: str,
        new_password: str,
        email_code: str,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        """Validate, verify the code, then secret, account, revocation, notice."""
        pending = await self._pending.get(reclaim_token)
        if pending is None:
            raise RegistrationExpiredError()
        errors = check_password(new_password)
        if errors:
            raise WeakPasswordError(params={"errors": errors})
        if pending.email is None:
            raise EmailNotSetError()
        account = await self._load(pending)
        await self._verifier.check(reclaim_token, email_code)
        # The secret goes first: the EMIS credentials are valid whatever happens next.
        await self._replace_secret(pending, account)
        await self._apply(pending, account, new_password, ip, user_agent)
        await self._revoker.revoke_everything(pending.user_id)
        await self._pending.delete(reclaim_token)
        await self._notify_old_email(account, pending)

    async def _load(self, pending: PendingReclaim) -> AccountSnapshot:
        """Check the account and the email before anything is written."""
        async with self._uow_factory() as uow:
            account = check_reclaimable(await uow.accounts.get(pending.user_id))
            await self._ensure_email_free(uow, str(pending.email), account)
        return account

    @staticmethod
    async def _ensure_email_free(
        uow: EmisUnitOfWork, email: str, account: AccountSnapshot
    ) -> None:
        if await uow.accounts.email_in_use(email, except_user_id=account.id):
            raise EmailInUseError(support_details="email belongs to another user")

    async def _replace_secret(
        self, pending: PendingReclaim, account: AccountSnapshot
    ) -> None:
        ref = account.emis_vault_ref
        if ref is None:  # check_reclaimable rules this out
            raise UserNotFoundError(support_details="account has no EMIS secret")
        with emis_errors():
            token = await self._store.decrypt(pending.token_enc)
            await self._store.replace(
                ref,
                login=pending.emis_login,
                password_enc=pending.password_enc,
                access_token=token,
            )

    async def _apply(
        self,
        pending: PendingReclaim,
        account: AccountSnapshot,
        new_password: str,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        email = str(pending.email)
        password_hash = await self._hasher.hash(new_password)
        async with self._uow_factory() as uow:
            check_reclaimable(await uow.accounts.get(account.id))
            await self._ensure_email_free(uow, email, account)
            await uow.accounts.set_credentials(
                account.id,
                password_hash=password_hash,
                recovery_email=email,
                now=self._clock.now(),
            )
            await uow.accounts.set_emis_status(account.id, "active")
            uow.audit(
                AuditDraft(
                    type="account.reclaimed",
                    user_id=account.id,
                    actor_id=account.id,
                    ip=ip,
                    user_agent=user_agent,
                    metadata={"emis_student_id": account.emis_student_id},
                )
            )
            await uow.commit()

    async def _notify_old_email(
        self, account: AccountSnapshot, pending: PendingReclaim
    ) -> None:
        """Tell the previous address; a mail failure must not undo the reclaim."""
        old = account.recovery_email
        if not old or old.lower() == str(pending.email).lower():
            return
        try:
            await self._email_sender.send(
                old,
                "notice",
                {"text_key": "id-mail-reclaimed-notice", "text_params": {}},
                account.locale,
            )
        except Exception:
            log.exception("reclaim notice failed", user_id=str(account.id))
