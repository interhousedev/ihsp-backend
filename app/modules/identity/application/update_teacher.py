"""PATCH /v1/admin/teachers/{id}: edit names (and the email before activation)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.activation_links import ActivationLinks
from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import USER_UPDATED
from app.modules.identity.domain.errors import (
    EmailLockedError,
    EmailTakenError,
    UserNotFoundError,
)
from app.modules.identity.domain.user import ActivationPurpose, User
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus


@dataclass(frozen=True, slots=True)
class UpdateTeacher:
    """The login never changes; the email only until the account is activated."""

    uow_factory: UowFactory
    links: ActivationLinks

    async def execute(
        self,
        actor: Actor,
        user_id: UUID,
        *,
        last_name: str | None,
        first_name: str | None,
        middle_name: str | None,
        email: str | None,
        ctx: RequestContext,
    ) -> User:
        """Apply the given fields; a new email re-sends the activation link."""
        resend_url: str | None = None
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            if Role.TEACHER not in user.roles:
                raise UserNotFoundError(params={"user_id": str(user_id)})
            if last_name is not None:
                user.last_name = last_name.strip()
            if first_name is not None:
                user.first_name = first_name.strip()
            if middle_name is not None:
                user.middle_name = middle_name.strip() or None
            if email is not None and email.strip().lower() != user.recovery_email:
                resend_url = await self._change_email(uow, user, email)
            await uow.users.save(user)
            uow.audit(
                make_audit(
                    USER_UPDATED, user_id=user_id, ctx=ctx, actor_id=actor.user_id
                )
            )
            await uow.commit()
        if resend_url:
            await self.links.send(user, resend_url)
        return user

    async def _change_email(
        self, uow: IdentityUnitOfWorkPort, user: User, email: str
    ) -> str:
        if user.status != UserStatus.PENDING_ACTIVATION:
            raise EmailLockedError()
        address = email.strip().lower()
        if await uow.users.email_taken(address, except_user_id=user.id):
            raise EmailTakenError()
        user.recovery_email = address
        return self.links.issue(user, ActivationPurpose.ACTIVATE)
