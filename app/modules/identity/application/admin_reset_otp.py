"""POST /v1/admin/users/{id}/reset-otp: remove the Telegram links of a user."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import OTP_RESET_BY_ADMIN
from app.modules.identity.domain.errors import AdminResetForbiddenError
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class AdminResetOtp:
    """OTP stays on; the lost Telegram accounts are unlinked at once."""

    uow_factory: UowFactory

    async def execute(self, actor: Actor, user_id: UUID, ctx: RequestContext) -> None:
        """Delete the links; an admin cannot reset their own OTP this way."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            if user.is_admin and user.id == actor.user_id:
                raise AdminResetForbiddenError()
            await uow.telegram_links.delete_all_for_user(user_id)
            user.otp_via_email = user.otp_enabled and user.has_verified_email
            user.clear_otp_reset()
            await uow.users.save(user)
            uow.audit(
                make_audit(
                    OTP_RESET_BY_ADMIN, user_id=user_id, ctx=ctx, actor_id=actor.user_id
                )
            )
            await uow.commit()
