"""Job identity.apply_otp_resets: remove Telegram links of due OTP resets."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.factor_support import reset_totp
from app.modules.identity.domain.audit_event import OTP_RESET_APPLIED
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class ApplyOtpResets:
    """After the 24 hour delay the lost Telegram accounts are unlinked (ID-24)."""

    uow_factory: UowFactory
    clock: Clock

    async def execute(self) -> int:
        """Return how many users were reset."""
        async with self.uow_factory() as uow:
            due = await uow.users.due_otp_resets(self.clock.now())
        for pending in due:
            await self._apply(pending.id)
        return len(due)

    async def _apply(self, user_id: UUID) -> None:
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None or user.otp_reset_effective_at is None:
                return
            await uow.telegram_links.delete_all_for_user(user.id)
            await reset_totp(uow, user.id)
            # OTP login stays on with the email channel only.
            user.otp_via_email = user.otp_enabled and user.has_verified_email
            user.clear_otp_reset()
            await uow.users.save(user)
            uow.audit(make_audit(OTP_RESET_APPLIED, user_id=user.id))
            await uow.commit()
