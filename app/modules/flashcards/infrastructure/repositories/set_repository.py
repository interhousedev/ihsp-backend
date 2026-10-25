"""SQL repository of flash card sets."""

from uuid import UUID

from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetSource
from app.modules.flashcards.infrastructure.orm.flashcard import Flashcard as CardRow
from app.modules.flashcards.infrastructure.orm.flashcard_set import (
    FlashcardSet as SetRow,
)

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: SetRow) -> FlashcardSet:
    return FlashcardSet(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        created_at=row.created_at,
        source=SetSource(row.source),
        description=row.description,
        source_chat_id=row.source_chat_id,
        copied_from_set_id=row.copied_from_set_id,
        new_per_day=int(row.new_per_day),
        reviews_per_day=int(row.reviews_per_day),
        card_count=int(row.card_count),
    )


def _apply(row: SetRow, entity: FlashcardSet) -> None:
    row.owner_id = entity.owner_id
    row.title = entity.title
    row.description = entity.description
    row.source = entity.source.value
    row.source_chat_id = entity.source_chat_id
    row.copied_from_set_id = entity.copied_from_set_id
    row.new_per_day = entity.new_per_day
    row.reviews_per_day = entity.reviews_per_day
    row.card_count = entity.card_count


class SqlFlashcardSetRepository:
    """Sets in `ai.flashcard_sets`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, flashcard_set: FlashcardSet) -> None:
        """Insert a new set."""
        row = SetRow(id=flashcard_set.id)
        row.created_at = flashcard_set.created_at
        row.updated_at = flashcard_set.created_at
        _apply(row, flashcard_set)
        self.session.add(row)
        await self.session.flush()

    async def _row(self, set_id: UUID, *, lock: bool) -> SetRow | None:
        stmt = select(SetRow).where(SetRow.id == set_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, set_id: UUID) -> FlashcardSet | None:
        """Return the set of any owner."""
        row = await self._row(set_id, lock=False)
        return _to_entity(row) if row else None

    async def get_for_update(self, set_id: UUID) -> FlashcardSet | None:
        """Return the set and lock its row until the transaction ends."""
        row = await self._row(set_id, lock=True)
        return _to_entity(row) if row else None

    async def save(self, flashcard_set: FlashcardSet) -> None:
        """Write the set's fields."""
        row = await self._row(flashcard_set.id, lock=False)
        if row is None:
            return
        _apply(row, flashcard_set)
        await self.session.flush()

    async def delete(self, set_id: UUID) -> None:
        """Delete the set with all its cards."""
        await self.session.execute(delete(CardRow).where(CardRow.set_id == set_id))
        await self.session.execute(delete(SetRow).where(SetRow.id == set_id))

    async def list_for_owner(self, owner_id: UUID) -> list[FlashcardSet]:
        """Return the owner's sets, newest first."""
        stmt = (
            select(SetRow)
            .where(SetRow.owner_id == owner_id)
            .order_by(SetRow.created_at.desc(), SetRow.id.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]
