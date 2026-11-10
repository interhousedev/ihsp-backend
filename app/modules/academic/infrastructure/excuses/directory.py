"""Who curates whom and who the people are, for excuses."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.excuses.ports import Person, StudentContext
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.student import Student
from app.shared.actor import Role
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlExcuseDirectory:
    """Implements ExcuseDirectory over the academic tables and the identity port."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        schedule: ScheduleQueries,
        identity: IdentityDirectory,
    ) -> None:
        """Store the session factory and the two ports."""
        self.sessionmaker = sessionmaker
        self.schedule = schedule
        self.identity = identity

    async def student_context(self, student_id: UUID) -> StudentContext | None:
        """The student's group and curator, or None for a user without a group."""
        student = await self.schedule.get_student(student_id)
        if student is None:
            return None
        async with self.sessionmaker() as session:
            curator = await session.scalar(
                select(Group.curator_id).where(Group.id == student.group_id)
            )
        return StudentContext(student_id, student.group_id, curator)

    async def curated_student_ids(self, curator_id: UUID) -> list[UUID]:
        """Active students of every group the user curates."""
        groups = await self.schedule.curated_group_ids(curator_id)
        if not groups:
            return []
        async with self.sessionmaker() as session:
            rows = await session.scalars(
                select(Student.user_id).where(
                    Student.group_id.in_(groups), Student.status == "active"
                )
            )
            return list(rows.all())

    async def people(self, user_ids: Sequence[UUID]) -> dict[UUID, Person]:
        """The users that exist."""
        users = await self.identity.get_users(list(user_ids))
        return {
            uid: Person(
                user_id=uid,
                name=f"{user.last_name} {user.first_name}".strip(),
                locale=getattr(user, "locale", None) or "ru",
            )
            for uid, user in users.items()
        }

    async def admin_ids(self) -> list[UUID]:
        """Every administrator."""
        return await self.identity.user_ids_with_roles([Role.ADMIN])
