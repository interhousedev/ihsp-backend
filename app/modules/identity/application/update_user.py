"""PATCH /v1/admin/users/{id}: edit any user's display name and email."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.activation_links import ActivationLinks
from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import EMAIL_CHANGED, USER_UPDATED
from app.modules.identity.domain.errors import EmailTakenError
from app.modules.identity.domain.user import ActivationPurpose, User
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.identity import UserStatus


class UserNameEmptyError(ValidationFailedError):
    """A name cannot be blank."""

    code = "id/name-empty"
    message_key = "id-name-empty"


@dataclass(frozen=True, slots=True)
class UpdateUser:
    """Names and the recovery email of any account; the login never changes."""

    uow_factory: UowFactory
    links: ActivationLinks
    clock: Clock

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
        """Apply the given fields (None keeps the value; a blank middle name clears).

        The email must be free (case-insensitive). The admin vouches for it, so it
        counts as verified; a pending account instead gets a new activation link.
        """
        resend_url: str | None = None
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            changed = _apply_names(user, last_name, first_name, middle_name)
            old_email = user.recovery_email
            if email is not None and email.strip().lower() != user.recovery_email:
                resend_url = await self._change_email(uow, user, email.strip().lower())
                changed.append("email")
            if changed:
                await uow.users.save(user)
                uow.audit(
                    make_audit(
                        USER_UPDATED,
                        user_id=user_id,
                        ctx=ctx,
                        actor_id=actor.user_id,
                        fields=changed,
                    )
                )
                if "email" in changed:
                    uow.audit(
                        make_audit(
                            EMAIL_CHANGED,
                            user_id=user_id,
                            ctx=ctx,
                            actor_id=actor.user_id,
                            previous=old_email,
                        )
                    )
                await uow.commit()
        if resend_url:
            await self.links.send(user, resend_url)
        return user

    async def _change_email(
        self, uow: IdentityUnitOfWorkPort, user: User, address: str
    ) -> str | None:
        """Store the free address; return an activation URL for a pending account."""
        if await uow.users.email_taken(address, except_user_id=user.id):
            raise EmailTakenError()
        user.recovery_email = address
        if user.status == UserStatus.PENDING_ACTIVATION:
            user.recovery_email_verified_at = None
            return self.links.issue(user, ActivationPurpose.ACTIVATE)
        user.recovery_email_verified_at = self.clock.now()
        return None


def _apply_names(
    user: User, last_name: str | None, first_name: str | None, middle_name: str | None
) -> list[str]:
    """Set the given names (trimmed) and return the fields that changed."""
    changed: list[str] = []
    for field, value in (("last_name", last_name), ("first_name", first_name)):
        if value is None:
            continue
        clean = value.strip()
        if not clean:
            raise UserNameEmptyError(params={"field": field})
        if clean != getattr(user, field):
            setattr(user, field, clean)
            changed.append(field)
    if middle_name is not None:
        clean_middle = middle_name.strip() or None
        if clean_middle != user.middle_name:
            user.middle_name = clean_middle
            changed.append("middle_name")
    return changed
