"""POST /v1/admin/users/{id}/reset-password: issue a password reset link."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.activation_links import ActivationLinks
from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import PASSWORD_RESET_BY_ADMIN
from app.modules.identity.domain.errors import (
    AdminResetForbiddenError,
    AdminTargetResetForbiddenError,
)
from app.modules.identity.domain.user import ActivationPurpose, User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class AdminResetPassword:
    """The link is returned to the admin and emailed to the user (ADM-5)."""

    uow_factory: UowFactory
    links: ActivationLinks

    async def execute(self, actor: Actor, user_id: UUID, ctx: RequestContext) -> str:
        """Return the activation URL; an admin cannot reset themselves this way."""
        user, url = await self.issue(actor, user_id, ctx)
        await self.links.send(user, url)
        return url

    async def issue(
        self,
        actor: Actor,
        user_id: UUID,
        ctx: RequestContext,
        *,
        refuse_admin_target: bool = False,
    ) -> tuple[User, str]:
        """Set the reset token, audit it and return (user, URL) without emailing.

        refuse_admin_target: the link-only route refuses Administration targets.
        """
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            if user.is_admin and user.id == actor.user_id:
                raise AdminResetForbiddenError()
            if refuse_admin_target and user.is_admin:
                raise AdminTargetResetForbiddenError()
            url = self.links.issue(user, ActivationPurpose.RESET_PASSWORD)
            await uow.users.save(user)
            uow.audit(
                make_audit(
                    PASSWORD_RESET_BY_ADMIN,
                    user_id=user_id,
                    ctx=ctx,
                    actor_id=actor.user_id,
                )
            )
            await uow.commit()
        return user, url
