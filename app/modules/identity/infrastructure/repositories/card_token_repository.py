"""SQLAlchemy repository of student card QR tokens (id.student_card_qr_tokens)."""

from uuid import UUID

from app.modules.identity.infrastructure.orm import StudentCardQrTokenRow

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlStudentCardTokens:
    """QR tokens in their own short transactions."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self._sessionmaker = sessionmaker

    async def ensure(self, user_id: UUID, candidate: str) -> str:
        """Insert the candidate unless a token exists; return the stored one."""
        stmt = (
            insert(StudentCardQrTokenRow)
            .values(user_id=user_id, token=candidate)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        async with self._sessionmaker.begin() as session:
            await session.execute(stmt)
            token = await session.scalar(
                select(StudentCardQrTokenRow.token).where(
                    StudentCardQrTokenRow.user_id == user_id
                )
            )
        assert token is not None
        return token

    async def replace(self, user_id: UUID, token: str) -> None:
        """Upsert the new token; the previous one no longer resolves."""
        stmt = insert(StudentCardQrTokenRow).values(user_id=user_id, token=token)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={"token": stmt.excluded.token, "created_at": func.now()},
        )
        async with self._sessionmaker.begin() as session:
            await session.execute(stmt)

    async def owner(self, token: str) -> UUID | None:
        """Return the student of a token."""
        stmt = select(StudentCardQrTokenRow.user_id).where(
            StudentCardQrTokenRow.token == token
        )
        async with self._sessionmaker() as session:
            owner: UUID | None = await session.scalar(stmt)
            return owner
