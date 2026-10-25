"""GET /v1/admin/users and /v1/admin/teachers: Administration lists."""

from dataclasses import dataclass

from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.pagination import Page


@dataclass(frozen=True, slots=True)
class ListUsers:
    """Search users by text, role and status with cursor pagination."""

    uow_factory: UowFactory

    async def execute(
        self,
        *,
        query: str | None,
        role: Role | None,
        status: UserStatus | None,
        cursor: str | None,
        limit: int,
    ) -> Page[User]:
        """Newest first."""
        async with self.uow_factory() as uow:
            return await uow.users.search(
                query=query,
                roles=[role] if role else [],
                status=status,
                cursor=cursor,
                limit=limit,
            )
