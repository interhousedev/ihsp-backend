"""SQLAlchemy repository of media grants."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.domain.learning.media_grant import MediaGrant
from app.modules.lms.infrastructure.orm.media_grant import MediaGrant as Row
from app.shared.ids import new_id

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: Row) -> MediaGrant:
    return MediaGrant(
        id=row.id,
        course_id=row.course_id,
        step_id=row.step_id,
        block_id=row.block_id,
        file_id=row.file_id,
        issued_to=row.issued_to,
        connector_id=row.connector_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        redeem_count=row.redeem_count,
    )


class SqlMediaGrantRepository:
    """Media grants of the lms schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def rotate(
        self,
        *,
        token_hash: str,
        course_id: UUID,
        step_id: UUID,
        block_id: str,
        file_id: UUID,
        issued_to: UUID,
        connector_id: UUID | None,
        expires_at: datetime,
    ) -> MediaGrant:
        """Atomically create or replace the one grant of (user, step, block)."""
        values = {
            "token_hash": token_hash,
            "course_id": course_id,
            "file_id": file_id,
            "connector_id": connector_id,
            "expires_at": expires_at,
            "revoked_at": None,
            "redeem_count": 0,
        }
        statement = (
            insert(Row)
            .values(
                id=new_id(),
                step_id=step_id,
                block_id=block_id,
                issued_to=issued_to,
                **values,
            )
            .on_conflict_do_update(
                constraint="uq_media_grants_issued_block", set_=values
            )
            .returning(Row)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(statement)).scalar_one()
        return _to_entity(row)

    async def get_by_hash(self, token_hash: str) -> MediaGrant | None:
        """Return the grant of a token."""
        row = await self.session.scalar(
            select(Row)
            .where(Row.token_hash == token_hash)
            .execution_options(populate_existing=True)
        )
        return _to_entity(row) if row else None

    async def add_redeem(self, grant_id: UUID) -> None:
        """Count one redeem."""
        await self.session.execute(
            update(Row)
            .where(Row.id == grant_id)
            .values(redeem_count=Row.redeem_count + 1)
        )

    async def revoke(self, grant_id: UUID, now: datetime) -> None:
        """Stop a grant."""
        await self.session.execute(
            update(Row)
            .where(Row.id == grant_id, Row.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_if_issued_to(
        self, grant_id: UUID, user_id: UUID, now: datetime
    ) -> bool:
        """Stop a grant of this user; False when it is not theirs or is missing."""
        found = await self.session.scalar(
            select(Row.id).where(Row.id == grant_id, Row.issued_to == user_id)
        )
        if found is None:
            return False
        await self.revoke(grant_id, now)
        return True

    async def list_for_user(self, user_id: UUID) -> list[MediaGrant]:
        """Return the user's grants, newest first."""
        rows = await self.session.scalars(
            select(Row)
            .where(Row.issued_to == user_id)
            .order_by(Row.expires_at.desc(), Row.id)
            .limit(200)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(row) for row in rows]
