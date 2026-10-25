"""POST /v1/id/me/sessions/revoke-others: log out everywhere else."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import SESSIONS_REVOKED
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class RevokeOtherSessions:
    """Revokes every session of the caller except the current one."""

    uow_factory: UowFactory
    revoker: AccessRevoker

    async def execute(self, actor: Actor, ctx: RequestContext) -> int:
        """Return how many sessions were revoked."""
        async with self.uow_factory() as uow:
            revoked = await self.revoker.revoke_sessions_in(
                uow, actor.user_id, except_id=actor.session_id
            )
            uow.audit(
                make_audit(
                    SESSIONS_REVOKED, user_id=actor.user_id, ctx=ctx, count=len(revoked)
                )
            )
            await uow.commit()
        return len(revoked)
