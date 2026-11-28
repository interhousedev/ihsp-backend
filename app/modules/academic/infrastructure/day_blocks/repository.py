"""PostgreSQL store of academic.day_blocks."""

from typing import cast
from uuid import UUID

from app.modules.academic.domain.day_blocks import (
    DayBlock,
    DayBlockKind,
    DayBlockScope,
)
from app.modules.academic.infrastructure.orm.day_block import DayBlock as DayBlockRow
from app.modules.academic.infrastructure.orm.group import Group as GroupRow
from app.modules.academic.infrastructure.orm.student import Student as StudentRow

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _to_domain(row: DayBlockRow) -> DayBlock:
    return DayBlock(
        id=row.id,
        name=row.name,
        kind=cast(DayBlockKind, row.kind),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        weekdays=list(row.weekdays),
        scope=cast(DayBlockScope, row.scope),
        course=row.course,
        group_ids=list(row.group_ids),
    )


class SqlDayBlockStore:
    """DayBlockStore over a session per call."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    async def list_all(self) -> list[DayBlock]:
        """Every block, ordered by start time and name."""
        async with self.sessionmaker() as session:
            rows = await session.scalars(
                select(DayBlockRow).order_by(
                    DayBlockRow.starts_at, DayBlockRow.name, DayBlockRow.id
                )
            )
            return [_to_domain(row) for row in rows]

    async def get(self, block_id: UUID) -> DayBlock | None:
        """One block, None when missing."""
        async with self.sessionmaker() as session:
            row = await session.get(DayBlockRow, block_id)
            return None if row is None else _to_domain(row)

    async def save(self, block: DayBlock) -> None:
        """Insert or update the block."""
        async with self.sessionmaker() as session:
            row = await session.get(DayBlockRow, block.id)
            if row is None:
                row = DayBlockRow(id=block.id)
                session.add(row)
            row.name = block.name
            row.kind = block.kind
            row.starts_at = block.starts_at
            row.ends_at = block.ends_at
            row.weekdays = block.weekdays
            row.scope = block.scope
            row.course = block.course
            row.group_ids = block.group_ids
            await session.commit()

    async def delete(self, block_id: UUID) -> bool:
        """Delete the block; False when it did not exist."""
        async with self.sessionmaker() as session:
            result = await session.execute(
                delete(DayBlockRow)
                .where(DayBlockRow.id == block_id)
                .returning(DayBlockRow.id)
            )
            deleted = result.scalar_one_or_none() is not None
            await session.commit()
            return deleted

    async def student_group(self, user_id: UUID) -> tuple[UUID, int | None] | None:
        """(group id, course of the group) of a student, None without a group."""
        async with self.sessionmaker() as session:
            row = (
                await session.execute(
                    select(StudentRow.group_id, GroupRow.course)
                    .join(GroupRow, GroupRow.id == StudentRow.group_id)
                    .where(StudentRow.user_id == user_id)
                )
            ).first()
        if row is None or row[0] is None:
            return None
        return (row[0], row[1])
