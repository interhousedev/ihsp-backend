"""GET /v1/admin/users/{id}: one account with sessions, Telegram and audit."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import STUDENT_VIEWED, AuditEventRecord
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock

RECENT_AUDIT = 20


@dataclass(frozen=True, slots=True)
class UserDetail:
    """Everything the Account tab shows."""

    user: User
    telegram: list[TelegramLink]
    sessions: list[LoginSession]
    recent_audit: list[AuditEventRecord]
    actors: dict[UUID, User]


@dataclass(frozen=True, slots=True)
class GetUserDetail:
    """Opening a student's profile is itself audited (GEN-6)."""

    uow_factory: UowFactory
    clock: Clock

    async def execute(
        self, actor: Actor, user_id: UUID, ctx: RequestContext
    ) -> UserDetail:
        """Load the account and record the view."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            links = await uow.telegram_links.list_for_user(user_id)
            sessions = await uow.sessions.list_active(user_id, self.clock.now())
            events = await uow.audit_events.recent_for_user(user_id, RECENT_AUDIT)
            actors = await uow.users.get_many(
                list({e.actor_id for e in events if e.actor_id})
            )
            if Role.STUDENT in user.roles:
                uow.audit(
                    make_audit(
                        STUDENT_VIEWED, user_id=user_id, ctx=ctx, actor_id=actor.user_id
                    )
                )
                await uow.commit()
        return UserDetail(user, links, sessions, events, actors)
