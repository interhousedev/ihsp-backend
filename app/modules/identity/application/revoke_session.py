"""DELETE /v1/id/me/sessions/{id}: log out one device."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import SESSION_REVOKED
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError


@dataclass(frozen=True, slots=True)
class RevokeSession:
    """Revokes a session of the caller (their own only)."""

    uow_factory: UowFactory
    revoker: AccessRevoker

    async def execute(
        self, actor: Actor, session_id: UUID, ctx: RequestContext
    ) -> None:
        """Revoke the session or raise NotFoundError."""
        async with self.uow_factory() as uow:
            revoked = await self.revoker.revoke_sessions_in(
                uow, actor.user_id, only_id=session_id
            )
            if not revoked:
                raise NotFoundError(params={"session_id": str(session_id)})
            uow.audit(
                make_audit(
                    SESSION_REVOKED,
                    user_id=actor.user_id,
                    ctx=ctx,
                    session_id=str(session_id),
                )
            )
            await uow.commit()
