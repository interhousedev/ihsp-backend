"""/v1/staff/lms/creators: LMS admins decide who may create courses."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.change_roles import ChangeRoles
from app.modules.identity.application.list_users import ListUsers
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from app.shared.pagination import Page


@dataclass(frozen=True, slots=True)
class ManageCourseCreators:
    """List, add and remove the holders of `lms_creator` (only for `lms_admin`).

    The role change itself, its rules for who may hold the role and its audit
    events are those of `ChangeRoles`.
    """

    users: ListUsers
    change_roles: ChangeRoles

    async def list(self, actor: Actor, *, cursor: str | None, limit: int) -> Page[User]:
        """Course creators, newest first."""
        actor.require(Role.LMS_ADMIN)
        return await self.users.execute(
            query=None, role=Role.LMS_CREATOR, status=None, cursor=cursor, limit=limit
        )

    async def add(self, actor: Actor, user_id: UUID, ctx: RequestContext) -> User:
        """Make a teacher or an administrator a course creator (idempotent)."""
        actor.require(Role.LMS_ADMIN)
        return await self.change_roles.execute(
            actor, user_id, grant=[Role.LMS_CREATOR], revoke=[], ctx=ctx
        )

    async def remove(self, actor: Actor, user_id: UUID, ctx: RequestContext) -> User:
        """Take the role away (idempotent); their courses stay theirs."""
        actor.require(Role.LMS_ADMIN)
        return await self.change_roles.execute(
            actor, user_id, grant=[], revoke=[Role.LMS_CREATOR], ctx=ctx
        )
