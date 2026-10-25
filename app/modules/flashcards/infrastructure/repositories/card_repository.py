"""SQL repository of flash cards."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.flashcard_set import SetCounts
from app.modules.flashcards.infrastructure.orm.flashcard import Flashcard as CardRow
from app.shared.srs import CardState, SrsState

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: CardRow) -> Flashcard:
    return Flashcard(
        id=row.id,
        set_id=row.set_id,
        position=row.position,
        front=row.front,
        back=row.back,
        srs=SrsState(
            state=CardState(row.state),
            step=int(row.step),
            due_at=row.due_at,
            interval_days=float(row.interval_days),
            ease=float(row.ease),
            reps=int(row.reps),
            lapses=int(row.lapses),
        ),
        last_reviewed_at=row.last_reviewed_at,
    )


def _apply(row: CardRow, entity: Flashcard) -> None:
    row.set_id = entity.set_id
    row.position = entity.position
    row.front = entity.front
    row.back = entity.back
    row.state = entity.srs.state.value
    row.step = entity.srs.step
    row.due_at = entity.srs.due_at
    row.interval_days = entity.srs.interval_days
    row.ease = entity.srs.ease
    row.reps = entity.srs.reps
    row.lapses = entity.srs.lapses
    row.last_reviewed_at = entity.last_reviewed_at


class SqlFlashcardRepository:
    """Cards in `ai.flashcards`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add_many(self, cards: Sequence[Flashcard]) -> None:
        """Insert new cards."""
        for card in cards:
            row = CardRow(id=card.id)
            _apply(row, card)
            self.session.add(row)
        await self.session.flush()

    async def _row(self, card_id: UUID, *, lock: bool) -> CardRow | None:
        stmt = select(CardRow).where(CardRow.id == card_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, card_id: UUID) -> Flashcard | None:
        """Return the card of any set."""
        row = await self._row(card_id, lock=False)
        return _to_entity(row) if row else None

    async def get_for_update(self, card_id: UUID) -> Flashcard | None:
        """Return the card and lock its row until the transaction ends."""
        row = await self._row(card_id, lock=True)
        return _to_entity(row) if row else None

    async def save(self, card: Flashcard) -> None:
        """Write the card's fields."""
        row = await self._row(card.id, lock=False)
        if row is None:
            return
        _apply(row, card)
        await self.session.flush()

    async def delete_many(self, card_ids: Sequence[UUID]) -> None:
        """Delete cards by id."""
        if not card_ids:
            return
        await self.session.execute(delete(CardRow).where(CardRow.id.in_(card_ids)))

    async def list_for_set(self, set_id: UUID) -> list[Flashcard]:
        """Return the set's cards ordered by position."""
        stmt = (
            select(CardRow)
            .where(CardRow.set_id == set_id)
            .order_by(CardRow.position, CardRow.id)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def counts_for_sets(
        self, set_ids: Sequence[UUID], *, due_before: datetime
    ) -> dict[UUID, SetCounts]:
        """Return new cards and seen cards due before `due_before`, per set."""
        if not set_ids:
            return {}
        is_new = CardRow.state == CardState.NEW.value
        learning = CardRow.state.in_(
            [CardState.LEARNING.value, CardState.RELEARNING.value]
        )
        review = CardRow.state == CardState.REVIEW.value
        due = ~is_new & (CardRow.due_at < due_before)
        stmt = (
            select(
                CardRow.set_id,
                func.count().filter(is_new),
                func.count().filter(due),
                func.count().filter(learning & due),
                func.count().filter(review & due),
            )
            .where(CardRow.set_id.in_(set_ids))
            .group_by(CardRow.set_id)
        )
        result = await self.session.execute(stmt)
        return {
            set_id: SetCounts(new=new, due=due_, learning=learn, review=rev)
            for set_id, new, due_, learn, rev in result.all()
        }
