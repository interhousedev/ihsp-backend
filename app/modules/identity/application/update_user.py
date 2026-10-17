"""PATCH /v1/admin/users/{id}: edit any user's names, login and recovery email."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.identity.application.activation_links import ActivationLinks
from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import EMAIL_CHANGED, USER_UPDATED
from app.modules.identity.domain.errors import EmailTakenError, LoginTakenError
from app.modules.identity.domain.login_name import check_login
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
    """Names, login and recovery email of any account, edited by Administration.

    A changed name or login is locked (``name_locked`` / ``login_locked``): the
    EMIS sync then keeps the manual value. A changed login revokes the user's
    sessions, as a password change does, except the admin's own session when the
    admin edits the own account.
    """

    uow_factory: UowFactory
    links: ActivationLinks
    clock: Clock
    revoker: AccessRevoker

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
        login: str | None = None,
    ) -> User:
        """Apply the given fields (None keeps the value; a blank middle name clears).

        The email must be free (case-insensitive). The admin vouches for it, so it
        counts as verified; a pending account instead gets a new activation link.
        The audit entry ``user.updated`` carries ``changes`` with old and new values.
        """
        resend_url: str | None = None
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            changes = _apply_names(user, last_name, first_name, middle_name)
            if changes:
                user.name_locked = True
            if login is not None:
                changes.update(await self._change_login(uow, user, login, actor, ctx))
            old_email = user.recovery_email
            if email is not None and email.strip().lower() != user.recovery_email:
                resend_url = await self._change_email(uow, user, email.strip().lower())
                changes["email"] = {"old": old_email, "new": user.recovery_email}
            if changes:
                await uow.users.save(user)
                uow.audit(
                    make_audit(
                        USER_UPDATED,
                        user_id=user_id,
                        ctx=ctx,
                        actor_id=actor.user_id,
                        fields=sorted(changes),
                        changes=changes,
                    )
                )
                if "email" in changes:
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

    async def _change_login(
        self,
        uow: IdentityUnitOfWorkPort,
        user: User,
        login: str,
        actor: Actor,
        ctx: RequestContext,
    ) -> dict[str, dict[str, Any]]:
        """Set a new login (checked, unique, locked); revoke the sessions."""
        new_login = check_login(login)
        old_login = user.login
        if new_login == (old_login or "").lower():
            return {}
        taken = await uow.users.get_by_login(new_login)
        if taken is not None and taken.id != user.id:
            raise LoginTakenError()
        user.login = new_login
        user.login_locked = True
        same_user = actor.user_id == user.id
        await self.revoker.revoke_sessions_in(
            uow,
            user.id,
            except_id=actor.session_id if same_user else None,
        )
        return {"login": {"old": old_login, "new": new_login}}

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
) -> dict[str, dict[str, Any]]:
    """Set the given names (trimmed); return the changed fields with old and new."""
    changes: dict[str, dict[str, Any]] = {}
    for field, value in (("last_name", last_name), ("first_name", first_name)):
        if value is None:
            continue
        clean = value.strip()
        if not clean:
            raise UserNameEmptyError(params={"field": field})
        old = getattr(user, field)
        if clean != old:
            setattr(user, field, clean)
            changes[field] = {"old": old, "new": clean}
    if middle_name is not None:
        clean_middle = middle_name.strip() or None
        if clean_middle != user.middle_name:
            changes["middle_name"] = {"old": user.middle_name, "new": clean_middle}
            user.middle_name = clean_middle
    return changes
