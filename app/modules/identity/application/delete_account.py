"""Ask for the deletion of a student's own account (UF-ID-16, ID-9, ID-29).

The password and the step-up code are checked here; the request itself is recorded
by the privacy module (``ErasureGateway``). An administrator approves it, which
makes the account ``pending_deletion`` (see ``AccountControlImpl``).
"""

from app.modules.identity.application.register_errors import (
    DeleteForbiddenError,
    OtpCodeInvalidError,
    WrongPasswordError,
)
from app.modules.identity.application.register_models import AccountSnapshot
from app.modules.identity.application.register_ports import (
    OtpPort,
    PasswordHasher,
    UnitOfWorkFactory,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from app.shared.contracts.privacy import ErasureGateway, ErasureTicket

STEP_UP_PURPOSE = "step-up"  # the code POST /v1/id/me/step-up sends, keyed by user id


class DeleteAccount:
    """Verify the owner, then record an erasure request for review."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        hasher: PasswordHasher,
        otp: OtpPort,
        erasure: ErasureGateway,
    ) -> None:
        """Store the collaborators."""
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._otp = otp
        self._erasure = erasure

    async def execute(
        self,
        actor: Actor,
        *,
        password: str,
        otp_code: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> ErasureTicket:
        """Check the password (and the step-up code); return the recorded request."""
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(actor.user_id)
        account = self._require_deletable(account)
        await self._check_password(account, password)
        await self._check_otp(account, otp_code)
        return await self._erasure.request(account.id, ip=ip, user_agent=user_agent)

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
