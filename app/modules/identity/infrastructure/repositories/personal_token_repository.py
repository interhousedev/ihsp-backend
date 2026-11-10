"""SQLAlchemy repository of personal tokens (id.personal_tokens)."""

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.identity.domain.personal_token import PersonalToken
from app.modules.identity.infrastructure.orm.personal_token import PersonalTokenRow

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: PersonalTokenRow) -> PersonalToken:
    return PersonalToken(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        prefix=row.prefix,
        token_hash=row.hash,
        scopes=list(row.scopes or []),
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


def _apply(row: PersonalTokenRow, token: PersonalToken) -> None:
    row.user_id = token.user_id
    row.name = token.name
    row.prefix = token.prefix
    row.hash = token.token_hash
    row.scopes = list(token.scopes)
    row.expires_at = token.expires_at
    row.last_used_at = token.last_used_at
    row.revoked_at = token.revoked_at


class SqlPersonalTokenRepository:
    """PersonalTokenRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self._session = session

    async def add(self, token: PersonalToken) -> None:
        """Insert a token."""
        row = PersonalTokenRow(id=token.id)
        _apply(row, token)
        self._session.add(row)
        await self._session.flush()

    async def get(self, token_id: UUID) -> PersonalToken | None:
        """Return the token or None."""
        row = await self._session.get(PersonalTokenRow, token_id)
        return _to_entity(row) if row else None

    async def get_by_hash(self, token_hash: str) -> PersonalToken | None:
        """Find a token by the hash of its secret."""
        row = await self._session.scalar(
            select(PersonalTokenRow).where(PersonalTokenRow.hash == token_hash)
        )
        return _to_entity(row) if row else None

    async def list_for_user(self, user_id: UUID) -> list[PersonalToken]:
        """Tokens of a user, newest first."""
        rows = await self._session.scalars(
            select(PersonalTokenRow)
            .where(PersonalTokenRow.user_id == user_id)
            .order_by(PersonalTokenRow.id.desc())
        )
        return [_to_entity(row) for row in rows]

    async def save(self, token: PersonalToken) -> None:
        """Write every field of an existing token."""
        row = await self._session.get(PersonalTokenRow, token.id)
        if row is None:
            raise LookupError(f"personal token {token.id} does not exist")
        _apply(row, token)
        await self._session.flush()

    async def touch_last_used(
        self, token_id: UUID, now: datetime, *, min_interval: timedelta
    ) -> None:
        """Set last_used_at unless it was updated within min_interval."""
        await self._session.execute(
            update(PersonalTokenRow)
            .where(
                PersonalTokenRow.id == token_id,
                or_(
                    PersonalTokenRow.last_used_at.is_(None),
                    PersonalTokenRow.last_used_at < now - min_interval,
                ),
            )
            .values(last_used_at=now)
        )
