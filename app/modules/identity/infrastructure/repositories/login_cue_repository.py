"""SQLAlchemy repository of login cues (id.login_cues)."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.identity.domain.login_cue import LoginCue
from app.modules.identity.infrastructure.orm import LoginCueRow

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _to_entity(row: LoginCueRow) -> LoginCue:
    return LoginCue(
        id=row.id,
        emis_login_enc=row.emis_login_enc,
        login_tail=row.login_tail,
        full_name=row.full_name,
        group_id=row.group_id,
        created_at=row.created_at,
        consumed_at=row.consumed_at,
        consumed_by_user_id=row.consumed_by_user_id,
    )


class SqlLoginCueRepository:
    """Login cues in their own short transactions."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self._sessionmaker = sessionmaker

    async def add(self, cues: Sequence[LoginCue]) -> None:
        """Insert the cues in one transaction."""
        rows = [
            LoginCueRow(
                id=cue.id,
                emis_login_enc=cue.emis_login_enc,
                login_tail=cue.login_tail,
                full_name=cue.full_name,
                group_id=cue.group_id,
                created_at=cue.created_at,
            )
            for cue in cues
        ]
        async with self._sessionmaker.begin() as session:
            session.add_all(rows)

    async def get(self, cue_id: UUID) -> LoginCue | None:
        """Return the cue with this id."""
        async with self._sessionmaker() as session:
            row = await session.get(LoginCueRow, cue_id)
        return None if row is None else _to_entity(row)

    async def list_cues(self, group_id: UUID | None = None) -> list[LoginCue]:
        """Return all cues, optionally of one group, newest first."""
        stmt = select(LoginCueRow).order_by(LoginCueRow.created_at.desc())
        if group_id is not None:
            stmt = stmt.where(LoginCueRow.group_id == group_id)
        async with self._sessionmaker() as session:
            return [_to_entity(row) for row in await session.scalars(stmt)]

    async def delete(self, cue_id: UUID) -> bool:
        """Delete the cue; False when it did not exist."""
        stmt = (
            delete(LoginCueRow)
            .where(LoginCueRow.id == cue_id)
            .returning(LoginCueRow.id)
        )
        async with self._sessionmaker.begin() as session:
            deleted = (await session.execute(stmt)).first()
        return deleted is not None

    async def open_group_ids(self) -> list[UUID]:
        """Return the groups that still have unconsumed cues."""
        stmt = (
            select(LoginCueRow.group_id)
            .where(LoginCueRow.consumed_at.is_(None))
            .distinct()
        )
        async with self._sessionmaker() as session:
            return list(await session.scalars(stmt))

    async def open_for_group(self, group_id: UUID) -> list[LoginCue]:
        """Return the unconsumed cues of one group, by name."""
        stmt = (
            select(LoginCueRow)
            .where(
                LoginCueRow.group_id == group_id,
                LoginCueRow.consumed_at.is_(None),
            )
            .order_by(LoginCueRow.full_name)
        )
        async with self._sessionmaker() as session:
            return [_to_entity(row) for row in await session.scalars(stmt)]

    async def reserve(
        self, cue_id: UUID, now: datetime, until: datetime
    ) -> LoginCue | None:
        """Hold the cue in one conditional UPDATE; a held or consumed cue gives None."""
        stmt = (
            update(LoginCueRow)
            .where(
                LoginCueRow.id == cue_id,
                LoginCueRow.consumed_at.is_(None),
                or_(
                    LoginCueRow.reserved_until.is_(None),
                    LoginCueRow.reserved_until <= now,
                ),
            )
            .values(reserved_until=until)
            .returning(LoginCueRow)
        )
        async with self._sessionmaker.begin() as session:
            row = (await session.scalars(stmt)).first()
            return None if row is None else _to_entity(row)

    async def release(self, cue_id: UUID) -> None:
        """Drop the hold of the cue."""
        stmt = (
            update(LoginCueRow)
            .where(LoginCueRow.id == cue_id)
            .values(reserved_until=None)
        )
        async with self._sessionmaker.begin() as session:
            await session.execute(stmt)

    async def claim(self, cue_id: UUID, now: datetime) -> bool:
        """Consume the cue in one conditional UPDATE, so only one claim wins."""
        stmt = (
            update(LoginCueRow)
            .where(LoginCueRow.id == cue_id, LoginCueRow.consumed_at.is_(None))
            .values(consumed_at=now, reserved_until=None)
            .returning(LoginCueRow.id)
        )
        async with self._sessionmaker.begin() as session:
            claimed = (await session.execute(stmt)).first()
        return claimed is not None
