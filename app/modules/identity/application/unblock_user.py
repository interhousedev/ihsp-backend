"""POST /v1/admin/users/{id}/unblock: restore a blocked account."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import USER_UNBLOCKED
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class UnblockUser:
    """Sessions were revoked at blocking, so the user has to sign in again."""

    uow_factory: UowFactory

    async def execute(self, actor: Actor, user_id: UUID, ctx: RequestContext) -> User:
        """Set the status back to active (the token verifier refreshes the epoch)."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            user.unblock()
            await uow.users.save(user)
            uow.audit(
                make_audit(
                    USER_UNBLOCKED, user_id=user_id, ctx=ctx, actor_id=actor.user_id
                )
            )
            await uow.commit()
        return user
