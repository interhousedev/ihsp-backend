"""POST /v1/admin/users/{id}/sessions/revoke: log a user out of every device."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import SESSIONS_REVOKED
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class RevokeUserSessions:
    """Administration revokes the sessions of another user."""

    uow_factory: UowFactory
    revoker: AccessRevoker

    async def execute(self, actor: Actor, user_id: UUID, ctx: RequestContext) -> int:
        """Return how many sessions were revoked."""
        async with self.uow_factory() as uow:
            await require_user(uow, user_id)
            revoked = await self.revoker.revoke_sessions_in(uow, user_id)
            uow.audit(
                make_audit(
                    SESSIONS_REVOKED,
                    user_id=user_id,
                    ctx=ctx,
                    actor_id=actor.user_id,
                    count=len(revoked),
                )
            )
            await uow.commit()
        return len(revoked)
