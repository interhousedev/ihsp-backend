"""Direct reads of the academic tables for assertions."""

from typing import Any
from uuid import UUID

from app.modules.academic.infrastructure.orm.mark import Mark
from app.modules.academic.infrastructure.orm.result import Result
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.sync_run import SyncRun

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]


async def marks_of(maker: Maker, user_id: UUID) -> list[Any]:
    """Return every mark row of the student, ordered by date, type and ordinal."""
    stmt = (
        sa.select(Mark)
        .where(Mark.student_id == user_id)
        .order_by(Mark.semester, Mark.date, Mark.type, Mark.value, Mark.ordinal)
    )
    async with maker() as session:
        return list((await session.execute(stmt)).scalars())


async def result_of(
    maker: Maker, user_id: UUID, semester: int, subject_id: UUID | None
) -> Any:
    """Return one result row (the GPA row for subject_id None) or None."""
    stmt = sa.select(Result).where(
        Result.student_id == user_id,
        Result.semester == semester,
        (
            Result.subject_id.is_(None)
            if subject_id is None
            else Result.subject_id == subject_id
        ),
    )
    async with maker() as session:
        return (await session.execute(stmt)).scalar_one_or_none()


async def student_of(maker: Maker, user_id: UUID) -> Any:
    """Return the student row."""
    async with maker() as session:
        return (
            await session.execute(sa.select(Student).where(Student.user_id == user_id))
        ).scalar_one()


async def runs(maker: Maker) -> list[Any]:
    """Return every sync run, oldest first."""
    async with maker() as session:
        return list(
            (
                await session.execute(sa.select(SyncRun).order_by(SyncRun.started_at))
            ).scalars()
        )
