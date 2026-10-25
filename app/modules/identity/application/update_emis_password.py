"""Replace the stored EMIS password after EMIS rejected the old one (UF-ID-12, ID-8)."""

from dataclasses import dataclass
from functools import partial
from typing import Literal
from uuid import UUID

from app.modules.identity.application.register_errors import (
    EmisProfileMismatchError,
    NoEmisLinkError,
    emis_errors,
)
from app.modules.identity.application.register_models import AccountSnapshot
from app.modules.identity.application.register_ports import (
    CredentialStore,
    EmisApi,
    UnitOfWorkFactory,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from app.shared.notifications import AuditDraft
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

ATTEMPTS_PER_HOUR = 10


@dataclass(frozen=True, slots=True)
class _Link:
    """The Vault reference and the EMIS profile id of an account."""

    ref: UUID
    emis_student_id: int


class UpdateEmisPassword:
    """Check the new EMIS password against EMIS before it replaces the secret."""

    def __init__(
        self,
        *,
        emis: EmisApi,
        store: CredentialStore,
        uow_factory: UnitOfWorkFactory,
        rate_limiter: RateLimiter,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self._emis = emis
        self._store = store
        self._uow_factory = uow_factory
        self._rate_limiter = rate_limiter
        self._kicker = kicker

    async def execute(
        self, actor: Actor, *, emis_password: str
    ) -> Literal["active", "needs_reauth"]:
        """Log in with the stored EMIS login and the new password, then store it."""
        actor.require(Role.STUDENT)
        await self._rate_limiter.hit(
            f"emis-password:{actor.user_id}",
            limit=ATTEMPTS_PER_HOUR,
            window_seconds=3600,
        )
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(actor.user_id)
        link = self._require_link(account)
        with emis_errors():
            secret = await self._store.read(link.ref)
            token = await self._emis.login(secret.login, emis_password)
            profile = await self._emis.profile(token)
            if profile.emis_student_id != link.emis_student_id:
                raise EmisProfileMismatchError(
                    support_details=f"emis {profile.emis_student_id}"
                )
            password_enc = await self._store.encrypt(emis_password)
            await self._store.replace(
                link.ref,
                login=secret.login,
                password_enc=password_enc,
                access_token=token,
            )
        await self._activate(actor)
        return "active"

    async def _activate(self, actor: Actor) -> None:
        async with self._uow_factory() as uow:
            await uow.accounts.set_emis_status(actor.user_id, "active")
            uow.audit(
                AuditDraft(
                    type="emis.password_updated",
                    user_id=actor.user_id,
                    actor_id=actor.user_id,
                )
            )
            uow.after_commit(
                partial(
                    self._kicker.kick,
                    "academic.sync_student",
                    user_id=str(actor.user_id),
                )
            )
            await uow.commit()

    @staticmethod
    def _require_link(account: AccountSnapshot | None) -> _Link:
        if (
            account is None
            or account.status is not UserStatus.ACTIVE
            or account.emis_vault_ref is None
            or account.emis_student_id is None
        ):
            raise NoEmisLinkError()
        return _Link(account.emis_vault_ref, account.emis_student_id)
