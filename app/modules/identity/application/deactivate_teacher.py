"""POST /v1/admin/teachers/{id}/deactivate: end a teacher's access (ADM-4)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import USER_DEACTIVATED
from app.modules.identity.domain.errors import (
    SelfActionForbiddenError,
    UserNotFoundError,
)
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.tasks import TaskKicker


@dataclass(frozen=True, slots=True)
class DeactivateTeacher:
    """Revokes access and asks academic to flag the teacher's future lessons."""

    uow_factory: UowFactory
    revoker: AccessRevoker
    kicker: TaskKicker

    async def execute(self, actor: Actor, user_id: UUID, ctx: RequestContext) -> User:
        """Deactivate the teacher account."""
        if actor.user_id == user_id:
            raise SelfActionForbiddenError()
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            if Role.TEACHER not in user.roles:
                raise UserNotFoundError(params={"user_id": str(user_id)})
            user.deactivate()
            await self.revoker.revoke_in(uow, user, keep_telegram=True)
            uow.audit(
                make_audit(
                    USER_DEACTIVATED, user_id=user_id, ctx=ctx, actor_id=actor.user_id
                )
            )

            async def kick() -> None:
                await self.kicker.kick(
                    "academic.teacher_deactivated", teacher_id=str(user_id)
                )

            uow.after_commit(kick)
            await uow.commit()
        return user
