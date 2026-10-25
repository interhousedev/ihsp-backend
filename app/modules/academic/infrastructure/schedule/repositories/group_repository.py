"""SQL repository of groups."""

from collections.abc import Collection
from uuid import UUID

from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.infrastructure.orm import Group as GroupRow
from app.modules.academic.infrastructure.schedule.mappers import (
    group_apply,
    group_new_row,
    group_to_entity,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlGroupRepository:
    """Groups in the academic schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, group_id: UUID) -> Group | None:
        """Return the group or None."""
        row = await self.session.get(GroupRow, group_id)
        return group_to_entity(row) if row else None

    async def get_many(self, group_ids: Collection[UUID]) -> dict[UUID, Group]:
        """Return the groups that exist, by id."""
        if not group_ids:
            return {}
        rows = await self.session.scalars(
            select(GroupRow).where(GroupRow.id.in_(list(group_ids)))
        )
        return {row.id: group_to_entity(row) for row in rows}

    async def get_by_emis_id(self, emis_group_id: int) -> Group | None:
        """Return the group linked to an EMIS group."""
        stmt = select(GroupRow).where(GroupRow.emis_group_id == emis_group_id)
        row = (await self.session.scalars(stmt.limit(1))).first()
        return group_to_entity(row) if row else None

    async def find_active_by_slug(self, slug: str) -> Group | None:
        """Return the active group with this slug."""
        stmt = select(GroupRow).where(
            GroupRow.slug == slug, GroupRow.status == "active"
        )
        row = (await self.session.scalars(stmt.limit(1))).first()
        return group_to_entity(row) if row else None

    async def add(self, group: Group) -> None:
        """Insert a group."""
        self.session.add(group_new_row(group))
        await self.session.flush()

    async def save(self, group: Group) -> None:
        """Write the changes of a group."""
        row = await self.session.get(GroupRow, group.id)
        if row is None:
            return
        group_apply(row, group)
        await self.session.flush()

    async def list_all(self, status: str | None = None) -> list[Group]:
        """Return groups ordered by name, optionally of one status."""
        stmt = select(GroupRow).order_by(GroupRow.name)
        if status is not None:
            stmt = stmt.where(GroupRow.status == status)
        return [group_to_entity(row) for row in await self.session.scalars(stmt)]

    async def curated_by(self, teacher_id: UUID) -> list[Group]:
        """Return the active groups a teacher curates."""
        stmt = (
            select(GroupRow)
            .where(GroupRow.curator_id == teacher_id, GroupRow.status == "active")
            .order_by(GroupRow.name)
        )
        return [group_to_entity(row) for row in await self.session.scalars(stmt)]
