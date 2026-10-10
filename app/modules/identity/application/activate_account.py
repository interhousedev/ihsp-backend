"""POST /v1/id/activation/{token}: set the password (and email) and activate."""

from dataclasses import dataclass

from app.modules.identity.application.activation_token import user_for_token
from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import PASSWORD_RESET, USER_ACTIVATED
from app.modules.identity.domain.errors import (
    EmailTakenError,
    OtpInvalidError,
    PasswordPolicyError,
)
from app.modules.identity.domain.password_policy import check_password
from app.modules.identity.domain.user import ActivationPurpose, User
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.identity import UserStatus
from app.shared.ids import hash_token


@dataclass(frozen=True, slots=True)
class ActivateAccount:
    """Finishes UF-ID-13 (activation) and the admin password reset link."""

    uow_factory: UowFactory
    hasher: PasswordHasher
    otp: OtpService
    tickets: TicketStore
    revoker: AccessRevoker
    clock: Clock
    urls: dict[str, str]

    async def execute(
        self,
        token: str,
        *,
        password: str,
        email: str | None,
        email_code: str | None,
        ctx: RequestContext,
    ) -> str:
        """Return where to send the user next."""
        errors = check_password(password)
        if errors:
            raise PasswordPolicyError(params={"errors": errors})
        async with self.uow_factory() as uow:
            user = await user_for_token(uow, token, self.clock)
            purpose = user.activation_purpose or ActivationPurpose.ACTIVATE
            if purpose == ActivationPurpose.ACTIVATE or not user.has_verified_email:
                await self._verify_email(uow, user, token, email, email_code)
            user.password_hash = await self.hasher.hash(password)
            user.password_change_required = False
            user.clear_activation()
            if user.status == UserStatus.PENDING_ACTIVATION:
                user.status = UserStatus.ACTIVE
            await uow.users.save(user)
            if purpose == ActivationPurpose.RESET_PASSWORD:
                await self.revoker.revoke_in(uow, user, keep_telegram=True)
            kind = (
                PASSWORD_RESET
                if purpose == ActivationPurpose.RESET_PASSWORD
                else USER_ACTIVATED
            )
            uow.audit(make_audit(kind, user_id=user.id, ctx=ctx))
            await uow.commit()
        return self._destination(user)

    async def _verify_email(
        self,
        uow: IdentityUnitOfWorkPort,
        user: User,
        token: str,
        email: str | None,
        email_code: str | None,
    ) -> None:
        if not email or not email_code:
            raise ValidationFailedError(params={"fields": ["email", "email_code"]})
        address = email.strip().lower()
        key = hash_token(token)
        pending = await self.tickets.get(f"activation-email:{key}")
        if pending is None or pending.get("email") != address:
            raise OtpInvalidError(params={"attempts_left": 0})
        await self.otp.check("activation-email", key, email_code)
        await self.tickets.delete(f"activation-email:{key}")
        if await uow.users.email_taken(address, except_user_id=user.id):
            raise EmailTakenError()
        user.recovery_email = address
        user.recovery_email_verified_at = self.clock.now()

    def _destination(self, user: User) -> str:
        if Role.ADMIN in user.roles:
            return self.urls["admin"]
        if Role.TEACHER in user.roles:
            return self.urls["staff"]
        return self.urls["sp"]
