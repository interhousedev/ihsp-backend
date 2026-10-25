"""Start reclaiming an account with EMIS credentials (UF-ID-15 steps 1-2)."""

from dataclasses import dataclass

from app.modules.identity.application.register_emis_login import VerifyEmisCredentials
from app.modules.identity.application.register_errors import (
    ReclaimForbiddenError,
    UserNotFoundError,
)
from app.modules.identity.application.register_models import (
    AccountSnapshot,
    PendingReclaim,
)
from app.modules.identity.application.register_ports import (
    PendingStore,
    UnitOfWorkFactory,
)
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus


@dataclass(frozen=True, slots=True)
class StartedReclaim:
    """The account found for the EMIS credentials."""

    reclaim_token: str
    login: str


def check_reclaimable(account: AccountSnapshot | None) -> AccountSnapshot:
    """Return the account if it can be reclaimed, else raise (ID-28)."""
    if account is None or account.status not in (UserStatus.ACTIVE, UserStatus.BLOCKED):
        raise UserNotFoundError()
    if account.status is UserStatus.BLOCKED or Role.ADMIN in account.roles:
        raise ReclaimForbiddenError(support_details=f"user {account.id}")
    if account.emis_vault_ref is None:
        raise UserNotFoundError(support_details="account has no EMIS secret")
    return account


class StartReclaim:
    """Verify EMIS credentials and find the account linked to that EMIS profile."""

    def __init__(
        self,
        *,
        verify: VerifyEmisCredentials,
        pending: PendingStore[PendingReclaim],
        uow_factory: UnitOfWorkFactory,
    ) -> None:
        """Store the collaborators."""
        self._verify = verify
        self._pending = pending
        self._uow_factory = uow_factory

    async def execute(
        self, *, emis_login: str, emis_password: str, ip: str | None
    ) -> StartedReclaim:
        """Throttled like registration; wrong credentials count toward the limits."""
        verified = await self._verify.execute(
            emis_login=emis_login, emis_password=emis_password, ip=ip
        )
        async with self._uow_factory() as uow:
            account = check_reclaimable(
                await uow.accounts.get_by_emis_student_id(
                    verified.profile.emis_student_id
                )
            )
        token = await self._pending.create(
            PendingReclaim(
                user_id=account.id,
                emis_login=verified.emis_login,
                password_enc=verified.password_enc,
                token_enc=verified.token_enc,
                locale=account.locale,
            )
        )
        return StartedReclaim(reclaim_token=token, login=account.login or "")
