"""SQL repository of the review log."""

from datetime import date, datetime
from uuid import UUID

from app.modules.flashcards.domain.review_log import ReviewLogEntry
from app.modules.flashcards.infrastructure.orm.flashcard_review import (
    FlashcardReview as ReviewRow,
)
from app.shared.clock import TASHKENT

from sqlalchemy import ColumnElement, Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _of_user(user_id: UUID, set_id: UUID | None) -> list[ColumnElement[bool]]:
    conditions = [ReviewRow.user_id == user_id]
    if set_id is not None:
        conditions.append(ReviewRow.set_id == set_id)
    return conditions


class SqlReviewLogRepository:
    """Log rows in `ai.flashcard_reviews`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, entry: ReviewLogEntry) -> None:
        """Insert one log row."""
        self.session.add(
            ReviewRow(
                id=entry.id,
                user_id=entry.user_id,
                set_id=entry.set_id,
                card_id=entry.card_id,
                rating=entry.rating.value,
                state_before=entry.state_before.value,
                interval_after_days=entry.interval_after_days,
                reviewed_at=entry.reviewed_at,
                duration_ms=entry.duration_ms,
            )
        )
        await self.session.flush()

    async def daily_counts(
        self, user_id: UUID, *, set_id: UUID | None
    ) -> dict[date, int]:
        """Return reviews per Tashkent day; one set, or all of the user's sets."""
        day = cast(func.timezone(TASHKENT.key, ReviewRow.reviewed_at), Date).label(
            "day"
        )
        stmt = select(day, func.count()).where(*_of_user(user_id, set_id)).group_by(day)
        return {row[0]: row[1] for row in (await self.session.execute(stmt)).all()}

    async def duration_ms_between(
        self,
        user_id: UUID,
        *,
        set_id: UUID | None,
        start: datetime,
        end: datetime,
    ) -> int:
        """Return the time spent on cards reviewed in [start, end), in milliseconds."""
        stmt = select(func.coalesce(func.sum(ReviewRow.duration_ms), 0)).where(
            *_of_user(user_id, set_id),
            ReviewRow.reviewed_at >= start,
            ReviewRow.reviewed_at < end,
        )
        total = (await self.session.execute(stmt)).scalar_one()
        return int(total or 0)
