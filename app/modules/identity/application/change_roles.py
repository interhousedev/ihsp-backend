"""POST /v1/admin/users/{id}/roles: grant or revoke Administration and LMS admin."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import ROLE_GRANTED, ROLE_REVOKED
from app.modules.identity.domain.errors import SelfActionForbiddenError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.notifications import AuditDraft

MANAGED_ROLES = frozenset({Role.ADMIN, Role.LMS_ADMIN})


@dataclass(frozen=True, slots=True)
class ChangeRoles:
    """Any role change logs the user out everywhere in the same transaction (ID-11)."""

    uow_factory: UowFactory
    revoker: AccessRevoker

    async def execute(
        self,
        actor: Actor,
        user_id: UUID,
        *,
        grant: Sequence[Role],
        revoke: Sequence[Role],
        ctx: RequestContext,
    ) -> User:
        """Apply the changes; nothing happens if no role really changes."""
        self._validate(actor, user_id, grant, revoke)
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            granted = [role for role in dict.fromkeys(grant) if user.grant(role)]
            revoked = [role for role in dict.fromkeys(revoke) if user.revoke(role)]
            if not granted and not revoked:
                return user
            await self.revoker.revoke_in(uow, user, keep_telegram=True)
            for role in granted:
                uow.audit(self._event(ROLE_GRANTED, role, user_id, actor, ctx))
            for role in revoked:
                uow.audit(self._event(ROLE_REVOKED, role, user_id, actor, ctx))
            await uow.commit()
        return user

    @staticmethod
    def _validate(
        actor: Actor, user_id: UUID, grant: Sequence[Role], revoke: Sequence[Role]
    ) -> None:
        if not set(grant) | set(revoke) <= MANAGED_ROLES:
            raise ValidationFailedError(params={"roles": ["admin", "lms_admin"]})
        if set(grant) & set(revoke):
            raise ValidationFailedError(params={"reason": "grant and revoke overlap"})
        if actor.user_id == user_id and Role.ADMIN in revoke:
            raise SelfActionForbiddenError()

    @staticmethod
    def _event(
        kind: str, role: Role, user_id: UUID, actor: Actor, ctx: RequestContext
    ) -> AuditDraft:
        return make_audit(
            kind, user_id=user_id, ctx=ctx, actor_id=actor.user_id, role=role.value
        )
