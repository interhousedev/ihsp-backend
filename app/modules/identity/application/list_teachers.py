"""GET /v1/admin/teachers: staff with the teacher role."""

from dataclasses import dataclass

from app.modules.identity.application.list_users import ListUsers
from app.modules.identity.domain.user import User
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.pagination import Page


@dataclass(frozen=True, slots=True)
class ListTeachers:
    """The users list filtered to teachers."""

    users: ListUsers

    async def execute(
        self,
        *,
        query: str | None,
        status: UserStatus | None,
        cursor: str | None,
        limit: int,
    ) -> Page[User]:
        """Newest first."""
        return await self.users.execute(
            query=query, role=Role.TEACHER, status=status, cursor=cursor, limit=limit
        )
