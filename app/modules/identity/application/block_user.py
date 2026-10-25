"""POST /v1/admin/users/{id}/block: block an account and log it out everywhere."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import USER_BLOCKED
from app.modules.identity.domain.errors import SelfActionForbiddenError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class BlockUser:
    """GEN-5: sessions, refresh tokens and connectors stop working at once."""

    uow_factory: UowFactory
    revoker: AccessRevoker

    async def execute(
        self, actor: Actor, user_id: UUID, reason: str, ctx: RequestContext
    ) -> User:
        """Block the user; Telegram links stay so unblocking restores the bot."""
        if actor.user_id == user_id:
            raise SelfActionForbiddenError()
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            user.block()
            await self.revoker.revoke_in(uow, user, keep_telegram=True)
            uow.audit(
                make_audit(
                    USER_BLOCKED,
                    user_id=user_id,
                    ctx=ctx,
                    actor_id=actor.user_id,
                    reason=reason,
                )
            )
            await uow.commit()
        return user
