"""POST /v1/admin/users/{id}/set-password: Administration sets an initial password."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.factor_support import enable_password_login
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import (
    PASSWORD_RESET_BY_ADMIN,
    USER_ACTIVATED,
)
from app.modules.identity.domain.errors import (
    AdminResetForbiddenError,
    PasswordPolicyError,
)
from app.modules.identity.domain.password_policy import check_password
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.identity import UserStatus


@dataclass(frozen=True, slots=True)
class AdminSetPassword:
    """For accounts without an email (teachers EMIS created) or a forgotten link."""

    uow_factory: UowFactory
    hasher: PasswordHasher
    revoker: AccessRevoker

    async def execute(
        self,
        actor: Actor,
        user_id: UUID,
        password: str,
        *,
        require_change: bool,
        ctx: RequestContext,
    ) -> None:
        """Store the password; a pending account becomes active and can sign in.

        ``require_change`` marks the password as temporary: when the deployment sets
        ``FEATURES__CHANGE_PASSWORD_ON_LOGIN`` the user must replace it at the next
        login. The user's sessions end, as after any password reset.
        """
        errors = check_password(password)
        if errors:
            raise PasswordPolicyError(params={"errors": errors})
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            if user.id == actor.user_id:
                raise AdminResetForbiddenError()
            user.password_hash = await self.hasher.hash(password)
            user.password_change_required = require_change
            await enable_password_login(uow, user.id)
            activated = user.status in (
                UserStatus.PENDING_ACTIVATION,
                UserStatus.UNREGISTERED,
            )
            if activated:
                user.status = UserStatus.ACTIVE
                user.clear_activation()
            await self.revoker.revoke_sessions_in(uow, user.id)
            await uow.users.save(user)
            uow.audit(
                make_audit(
                    PASSWORD_RESET_BY_ADMIN,
                    user_id=user_id,
                    ctx=ctx,
                    actor_id=actor.user_id,
                    mode="set",
                    require_change=require_change,
                )
            )
            if activated:
                uow.audit(
                    make_audit(
                        USER_ACTIVATED,
                        user_id=user_id,
                        ctx=ctx,
                        actor_id=actor.user_id,
                    )
                )
            await uow.commit()
