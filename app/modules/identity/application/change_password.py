"""POST /v1/id/me/password: change the password and log out the other devices."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import PASSWORD_CHANGED
from app.modules.identity.domain.errors import (
    InvalidCredentialsError,
    PasswordPolicyError,
)
from app.modules.identity.domain.password_policy import check_password
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.rate_limit import RateLimiter


@dataclass(frozen=True, slots=True)
class ChangePassword:
    """Needs the current password; keeps only the caller's session."""

    uow_factory: UowFactory
    hasher: PasswordHasher
    revoker: AccessRevoker
    rate_limiter: RateLimiter

    async def execute(
        self,
        actor: Actor,
        current_password: str,
        new_password: str,
        ctx: RequestContext,
    ) -> None:
        """Set the new password after checking the current one and the policy."""
        await self.rate_limiter.hit(
            f"pw-change:{actor.user_id}", limit=5, window_seconds=3600
        )
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if not await self.hasher.verify(user.password_hash, current_password):
                raise InvalidCredentialsError()
            errors = check_password(new_password)
            if errors:
                raise PasswordPolicyError(params={"errors": errors})
            user.password_hash = await self.hasher.hash(new_password)
            await uow.users.save(user)
            await self.revoker.revoke_sessions_in(
                uow, user.id, except_id=actor.session_id
            )
            uow.audit(make_audit(PASSWORD_CHANGED, user_id=user.id, ctx=ctx))
            await uow.commit()
