"""POST /v1/admin/users: an account for staff-like people, joined by Telegram invite."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.telegram_onboarding import (
    INVITE_PREFIX,
    TelegramOnboarding,
)
from app.modules.identity.domain.audit_event import USER_CREATED
from app.modules.identity.domain.errors import (
    EmailTakenError,
    InvitedRoleForbiddenError,
    InvitedRolesRequiredError,
)
from app.modules.identity.domain.login_name import base_login, next_free
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import AccountKind, UserStatus
from app.shared.ids import new_id

# Students and teachers come from EMIS or the teacher route.
INVITABLE_ROLES = frozenset(
    {
        Role.ADMIN,
        Role.LIBRARIAN,
        Role.LMS_ADMIN,
        Role.LMS_CREATOR,
        Role.COUNSELOR,
        Role.MENTOR,
        Role.TRANSCRIPT_OFFICER,
    }
)


@dataclass(frozen=True, slots=True)
class InvitedUserCreated:
    """The new account and its one-time Telegram invitation."""

    user: User
    invite_url: str


@dataclass(frozen=True, slots=True)
class CreateInvitedUser:
    """Create a non-student, non-teacher account and issue ``inv_<code>``."""

    uow_factory: UowFactory
    onboarding: TelegramOnboarding
    bot_username: str

    async def execute(
        self,
        actor: Actor,
        *,
        last_name: str,
        first_name: str,
        middle_name: str | None,
        account_kind: AccountKind,
        roles: Sequence[Role],
        email: str | None,
        phone: str | None,
        ctx: RequestContext,
    ) -> InvitedUserCreated:
        """Validate, store the account (active, no password) and issue the link."""
        actor.require(Role.ADMIN)
        wanted = set(roles)
        if not wanted:
            raise InvitedRolesRequiredError()
        if not wanted <= INVITABLE_ROLES:
            raise InvitedRoleForbiddenError(
                params={"roles": sorted(r.value for r in INVITABLE_ROLES)}
            )
        address = (email or "").strip().lower() or None
        async with self.uow_factory() as uow:
            if address and await uow.users.email_taken(address):
                raise EmailTakenError()
            base = base_login(last_name, first_name)
            login = next_free(base, await uow.users.logins_with_prefix(base))
            user = User(
                id=new_id(),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                middle_name=(middle_name or "").strip() or None,
                login=login,
                roles=wanted,
                recovery_email=address,
                phone=(phone or "").strip() or None,
                status=UserStatus.ACTIVE,
                account_kind=account_kind,
            )
            await uow.users.add(user)
            uow.audit(
                make_audit(
                    USER_CREATED,
                    user_id=user.id,
                    ctx=ctx,
                    actor_id=actor.user_id,
                    roles=sorted(r.value for r in wanted),
                    account_kind=account_kind.value,
                )
            )
            await uow.commit()
        code = await self.onboarding.issue_invite(user.id)
        return InvitedUserCreated(
            user=user,
            invite_url=f"https://t.me/{self.bot_username}?start={INVITE_PREFIX}{code}",
        )
