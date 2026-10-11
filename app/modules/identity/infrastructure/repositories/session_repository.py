"""SQLAlchemy repository of login sessions (id.sessions)."""

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.identity.domain.session import LoginSession
from app.modules.identity.infrastructure.orm import Session as SessionRow

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: SessionRow) -> LoginSession:
    return LoginSession(
        id=row.id,
        user_id=row.user_id,
        ip=row.ip,
        user_agent=row.user_agent,
        expires_at=row.expires_at,
        last_seen_at=row.last_seen_at,
        hydra_sid=row.hydra_sid,
        amr=list(row.amr or []),
        mfa_at=row.mfa_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


class SqlSessionRepository:
    """SessionRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self._session = session

    async def add(self, session: LoginSession) -> None:
        """Insert a session."""
        self._session.add(
            SessionRow(
                id=session.id,
                user_id=session.user_id,
                hydra_sid=session.hydra_sid,
                amr=list(session.amr),
                mfa_at=session.mfa_at,
                ip=session.ip,
                user_agent=session.user_agent,
                last_seen_at=session.last_seen_at,
                expires_at=session.expires_at,
                revoked_at=session.revoked_at,
            )
        )
        await self._session.flush()

    async def save(self, session: LoginSession) -> None:
        """Write every field of an existing session."""
        row = await self._session.get(SessionRow, session.id)
        if row is None:
            raise LookupError(f"session {session.id} does not exist")
        row.hydra_sid = session.hydra_sid
        row.amr = list(session.amr)
        row.mfa_at = session.mfa_at
        row.ip = session.ip
        row.user_agent = session.user_agent
        row.last_seen_at = session.last_seen_at
        row.expires_at = session.expires_at
        row.revoked_at = session.revoked_at
        await self._session.flush()

    async def get(self, session_id: UUID) -> LoginSession | None:
        """Return the session or None."""
        row = await self._session.get(SessionRow, session_id)
        return _to_entity(row) if row else None

    async def get_by_hydra_sid(self, hydra_sid: str) -> LoginSession | None:
        """Return the session that belongs to a Hydra login session."""
        row = await self._session.scalar(
            select(SessionRow).where(SessionRow.hydra_sid == hydra_sid)
        )
        return _to_entity(row) if row else None

    async def list_active(self, user_id: UUID, now: datetime) -> list[LoginSession]:
        """Active sessions of a user, most recently seen first."""
        rows = await self._session.scalars(
            select(SessionRow)
            .where(
                SessionRow.user_id == user_id,
                SessionRow.revoked_at.is_(None),
                SessionRow.expires_at > now,
            )
            .order_by(SessionRow.last_seen_at.desc(), SessionRow.id.desc())
        )
        return [_to_entity(row) for row in rows]

    async def latest_active(
        self, user_id: UUID, now: datetime, *, amr: list[str] | None = None
    ) -> LoginSession | None:
        """The most recently created active session of a user (optionally by amr)."""
        query = select(SessionRow).where(
            SessionRow.user_id == user_id,
            SessionRow.revoked_at.is_(None),
            SessionRow.expires_at > now,
        )
        if amr is not None:
            query = query.where(SessionRow.amr == amr)
        row = await self._session.scalar(
            query.order_by(SessionRow.created_at.desc(), SessionRow.id.desc()).limit(1)
        )
        return _to_entity(row) if row else None

    async def revoke(self, session_id: UUID, now: datetime) -> LoginSession | None:
        """Revoke one active session; return it, or None if it was not active."""
        row = await self._session.scalar(
            update(SessionRow)
            .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(SessionRow)
            .execution_options(populate_existing=True)
        )
        return _to_entity(row) if row else None

    async def revoke_all(
        self, user_id: UUID, now: datetime, *, except_id: UUID | None = None
    ) -> list[LoginSession]:
        """Revoke every active session of a user (except one); return them."""
        stmt = (
            update(SessionRow)
            .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(SessionRow)
            .execution_options(populate_existing=True)
        )
        if except_id is not None:
            stmt = stmt.where(SessionRow.id != except_id)
        rows = await self._session.scalars(stmt)
        return [_to_entity(row) for row in rows]

    async def touch(
        self, session_id: UUID, now: datetime, *, min_interval: timedelta
    ) -> None:
        """Set last_seen_at unless it was updated within min_interval."""
        await self._session.execute(
            update(SessionRow)
            .where(
                SessionRow.id == session_id,
                SessionRow.last_seen_at < now - min_interval,
            )
            .values(last_seen_at=now)
        )
