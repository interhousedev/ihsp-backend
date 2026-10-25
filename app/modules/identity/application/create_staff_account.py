"""Create a staff account (teacher or Administration) without EMIS (ID-10)."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.activation_links import ActivationLinks
from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import USER_CREATED
from app.modules.identity.domain.errors import EmailTakenError, LoginTakenError
from app.modules.identity.domain.login_name import base_login, next_free
from app.modules.identity.domain.user import ActivationPurpose, User
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class StaffCreated:
    """The new account and its activation link."""

    user: User
    activation_url: str


@dataclass(frozen=True, slots=True)
class CreateStaffAccount:
    """Generates the login, stores the account as pending and emails the link."""

    uow_factory: UowFactory
    links: ActivationLinks

    async def execute(
        self,
        *,
        actor_id: UUID | None,
        last_name: str,
        first_name: str,
        middle_name: str | None,
        email: str,
        roles: Sequence[Role],
        login: str | None = None,
        ctx: RequestContext | None = None,
    ) -> StaffCreated:
        """Create the account; ``login`` is generated unless given (CLI)."""
        address = email.strip().lower()
        async with self.uow_factory() as uow:
            if await uow.users.email_taken(address):
                raise EmailTakenError()
            chosen = await self._login(uow, last_name, first_name, login)
            user = User(
                id=new_id(),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                middle_name=(middle_name or "").strip() or None,
                login=chosen,
                roles=set(roles),
                recovery_email=address,
                status=UserStatus.PENDING_ACTIVATION,
            )
            url = self.links.issue(user, ActivationPurpose.ACTIVATE)
            await uow.users.add(user)
            uow.audit(
                make_audit(
                    USER_CREATED,
                    user_id=user.id,
                    ctx=ctx,
                    actor_id=actor_id,
                    roles=sorted(role.value for role in roles),
                )
            )
            await uow.commit()
        await self.links.send(user, url)
        return StaffCreated(user=user, activation_url=url)

    @staticmethod
    async def _login(
        uow: IdentityUnitOfWorkPort,
        last_name: str,
        first_name: str,
        requested: str | None,
    ) -> str:
        if requested:
            if await uow.users.get_by_login(requested) is not None:
                raise LoginTakenError()
            return requested.strip().lower()
        base = base_login(last_name, first_name)
        taken = await uow.users.logins_with_prefix(base)
        return next_free(base, taken)
