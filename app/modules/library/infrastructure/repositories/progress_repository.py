"""SQL repository of reading progress."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.domain.reader_progress import ReadingProgress
from app.modules.library.infrastructure.orm import ReadingProgress as ProgressRow
from app.modules.library.infrastructure.repositories.rowcount import rows_affected

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

FINISHED = 100


def _progress_from(row: ProgressRow) -> ReadingProgress:
    return ReadingProgress(
        user_id=row.user_id,
        item_id=row.item_id,
        file_id=row.file_id,
        locator=dict(row.locator),
        percent=float(row.percent),
        opened_at=row.opened_at,
        seconds_read=row.seconds_read,
        client_ts=row.client_ts,
    )


class SqlProgressRepository:
    """Stores progress in `library.reading_progress`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def percents(
        self, user_id: UUID, item_ids: Sequence[UUID]
    ) -> dict[UUID, float]:
        """Progress 0 to 100 of the items the user has opened (others are absent)."""
        if not item_ids:
            return {}
        rows = await self.session.execute(
            select(ProgressRow.item_id, ProgressRow.percent).where(
                ProgressRow.user_id == user_id, ProgressRow.item_id.in_(set(item_ids))
            )
        )
        return {item_id: float(percent) for item_id, percent in rows.all()}

    # - - - Added by the reader area - - -

    async def get(self, user_id: UUID, item_id: UUID) -> ReadingProgress | None:
        """The user's progress in the item, or None."""
        row = await self.session.get(ProgressRow, (user_id, item_id))
        return _progress_from(row) if row else None

    async def save(self, progress: ReadingProgress) -> None:
        """Insert the progress or replace the existing row of the user and item."""
        values = {
            "file_id": progress.file_id,
            "locator": progress.locator,
            "percent": progress.percent,
            "opened_at": progress.opened_at,
            "seconds_read": progress.seconds_read,
            "client_ts": progress.client_ts,
            "updated_at": progress.client_ts,
        }
        statement = insert(ProgressRow).values(
            user_id=progress.user_id,
            item_id=progress.item_id,
            created_at=progress.client_ts,
            **values,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[ProgressRow.user_id, ProgressRow.item_id], set_=values
            )
        )

    async def unfinished(
        self, user_id: UUID, *, limit: int, offset: int = 0
    ) -> list[ReadingProgress]:
        """Progress below 100 percent, most recently opened first."""
        rows = await self.session.execute(
            select(ProgressRow)
            .where(ProgressRow.user_id == user_id, ProgressRow.percent < FINISHED)
            .order_by(ProgressRow.opened_at.desc(), ProgressRow.item_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_progress_from(row) for row in rows.scalars()]

    async def delete_all(self, user_id: UUID) -> int:
        """Delete all progress of the user (account closure)."""
        result = await self.session.execute(
            delete(ProgressRow).where(ProgressRow.user_id == user_id)
        )
        return rows_affected(result)
