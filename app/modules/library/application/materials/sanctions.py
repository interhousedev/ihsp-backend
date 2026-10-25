"""Warnings and upload bans set by Administration (LIB-14)."""

from datetime import datetime
from uuid import UUID

from app.modules.library.domain.enums import SanctionKind
from app.modules.library.domain.moderation_entities import Sanction
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.library_audit import LibraryAuditType
from app.shared.notifications import AuditDraft

REASON_MAX = 2000


class CreateSanction:
    """Administration warns a user or bans them from uploading."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, identity: IdentityDirectory
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity

    async def execute(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        kind: SanctionKind,
        until: datetime | None,
        reason: str,
    ) -> Sanction:
        """Store the sanction and audit it; a warning has no end date."""
        actor.require(Role.ADMIN)
        reason = reason.strip()
        now = self.clock.now()
        if not reason or len(reason) > REASON_MAX:
            raise ValidationFailedError(params={"field": "reason"})
        if kind is SanctionKind.WARNING:
            until = None
        elif until is not None and until <= now:
            raise ValidationFailedError(params={"field": "until"})
        if await self.identity.get_user(user_id) is None:
            raise ValidationFailedError(params={"field": "user_id"})
        sanction = Sanction(
            id=new_id(),
            user_id=user_id,
            kind=kind,
            reason=reason,
            set_by=actor.user_id,
            created_at=now,
            until=until,
        )
        async with self.uow_factory() as uow:
            await uow.moderation.add_sanction(sanction)
            uow.audit(
                AuditDraft(
                    type=LibraryAuditType.SANCTION.value,
                    user_id=user_id,
                    actor_id=actor.user_id,
                    metadata={
                        "sanction_id": str(sanction.id),
                        "kind": kind.value,
                        "until": until.isoformat() if until else None,
                        "reason": reason,
                    },
                )
            )
            await uow.commit()
        return sanction


class ListSanctions:
    """Administration reads the sanctions, optionally of one user."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, *, user_id: UUID | None) -> list[Sanction]:
        """Newest first."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            return await uow.moderation.list_sanctions(user_id)
